"""图片解码服务：后台线程、按屏宽缩放解码、LRU 缓存与相邻预取。

关键点：
- 解码与 EXIF 读取全部在 ``QThreadPool`` 里完成，UI 线程零 IO；
- 只解码到需要显示的尺寸（``QImageReader.setScaledSize``），避免几十 MB 的原图常驻内存；
- 切换照片时用递增的 generation 抢占旧任务，连按方向键不会排队卡住；
- 缓存按字节数做 LRU 淘汰。
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, replace
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QImage, QImageReader

from livephoto_player.core.livephoto import find_video_span
from livephoto_player.core.models import ImagePayload
from livephoto_player.services.browser import IMAGE_EXTENSIONS
from livephoto_player.utils.logger import get_logger

MAX_FULL_PIXELS = 150_000_000
# 超过该像素数才考虑用整数分之一预缩小，其余一律全解码保证锐度
HUGE_IMAGE_PIXELS = 40_000_000
PREVIEW_BUCKET = 256
_CACHE_BUDGET = 320 * 1024 * 1024
_MAX_PENDING = 10

_EXIF_DATETIME_ORIGINAL = 36867
_EXIF_DATETIME = 306

_heif_ready = False


def _ensure_heif_support() -> bool:
    """按需注册 HEIC/HEIF 解码器；失败只记日志，不影响其它格式。"""
    global _heif_ready
    if _heif_ready:
        return True
    try:
        import pillow_heif

        pillow_heif.register_heif_opener()
    except Exception as exc:  # noqa: BLE001 - 缺少可选依赖时降级
        get_logger("image").warning("HEIC 解码器不可用：%s", exc)
        return False
    _heif_ready = True
    return True


def _read_taken_at(path: Path) -> str:
    """用 Pillow 读取拍摄时间；失败返回空串。"""
    try:
        from PIL import Image

        with Image.open(path) as image:
            exif = image.getexif()
            for tag in (_EXIF_DATETIME_ORIGINAL, _EXIF_DATETIME):
                value = exif.get(tag)
                if isinstance(value, str) and value:
                    return value.replace(":", "-", 2)
    except Exception:  # noqa: BLE001 - EXIF 属于展示信息，失败不应影响加载
        return ""
    return ""


def _decode_with_pillow(path: Path, target_width: int, *, full: bool) -> QImage:
    """Qt 无法解码时的兜底路径（主要服务于 HEIC）。"""
    if not _ensure_heif_support():
        return QImage()
    from PIL import Image

    try:
        with Image.open(path) as image:
            converted = image.convert("RGB")
            if not full and target_width > 0 and converted.width > target_width:
                ratio = target_width / converted.width
                converted = converted.resize(
                    (target_width, max(1, int(converted.height * ratio))),
                    Image.Resampling.LANCZOS,
                )
            width, height = converted.size
            if width * height > MAX_FULL_PIXELS:
                return QImage()
            buffer = converted.tobytes()
    except (OSError, ValueError) as exc:
        get_logger("image").warning("Pillow 解码失败 %s：%s", path, exc)
        return QImage()
    return QImage(buffer, width, height, 3 * width, QImage.Format.Format_RGB888).copy()


def _read_scaled(reader: QImageReader, source: QSize, target_width: int) -> QImage:
    """按目标宽度解码。

    关键点：**不把最终尺寸交给 ``QImageReader.setScaledSize``**。Qt 的 JPEG 解码器
    会用 libjpeg 的非整数比例采样，实测比「全解码 + 平滑缩放」软 20~40%
    （拉普拉斯方差 2230 vs 3548），画面明显发糊。

    因此这里只在超大图上用整数分之一（1/2、1/4…）做一次高质量预缩小，
    其余情况一律全解码，再由本函数自己做平滑缩放。
    """
    pixels = source.width() * source.height() if source.isValid() else 0
    if pixels > HUGE_IMAGE_PIXELS and target_width > 0:
        factor = 2
        while factor < 8 and source.width() // factor > target_width * 2:
            factor *= 2
        reader.setScaledSize(QSize(source.width() // factor, source.height() // factor))
    image = reader.read()
    if image.isNull() or target_width <= 0 or image.width() <= target_width:
        return image
    ratio = target_width / image.width()
    return image.scaled(
        target_width,
        max(1, round(image.height() * ratio)),
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def decode_image(path: Path, target_width: int, *, full: bool = False) -> tuple[QImage, QSize]:
    """解码图片；``full=False`` 时缩放到目标宽度，同时返回原始像素尺寸。"""
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    source = reader.size()
    if not source.isValid():
        source = QSize()
    if full or not source.isValid() or target_width <= 0:
        image = reader.read()
        if image.isNull():
            fallback = _decode_with_pillow(path, target_width, full=full)
            if fallback.isNull():
                get_logger("image").error("解码失败 %s：%s", path, reader.errorString())
                return QImage(), source
            return fallback, QSize(fallback.width(), fallback.height())
        return image, source

    image = _read_scaled(reader, source, target_width)
    if not image.isNull():
        return image, source
    fallback = _decode_with_pillow(path, target_width, full=full)
    if fallback.isNull():
        get_logger("image").error("解码失败 %s：%s", path, reader.errorString())
        return QImage(), source
    return fallback, source


def bucket_for(width: int) -> int:
    """把目标宽度量化到桶，避免窗口轻微变化导致缓存全部失效。"""
    if width <= 0:
        return 0
    return max(PREVIEW_BUCKET, (width + PREVIEW_BUCKET - 1) // PREVIEW_BUCKET * PREVIEW_BUCKET)


@dataclass(frozen=True, slots=True)
class _Request:
    path: Path
    target_width: int
    generation: int
    prefetch: bool
    full: bool

    @property
    def bucket(self) -> int:
        return 0 if self.full else bucket_for(self.target_width)


class _TaskSignals(QObject):
    finished = Signal(int, object)


class _DecodeTask(QRunnable):
    """单个解码任务；异常一律转成带 ``error`` 的 payload。"""

    def __init__(self, task_id: int, request: _Request, signals: _TaskSignals) -> None:
        super().__init__()
        self.task_id = task_id
        self._request = request
        self._signals = signals

    def run(self) -> None:
        request = self._request
        try:
            image, source = decode_image(request.path, request.target_width, full=request.full)
            span = None
            if (
                not image.isNull()
                and not request.full
                and request.path.suffix.lower() in IMAGE_EXTENSIONS
            ):
                # 预取同样探测内嵌视频：缓存命中也必须带上 span，
                # 否则被预取的实况照片会被误判成普通照片。
                span = find_video_span(request.path)
            if image.isNull():
                payload = ImagePayload(
                    path=request.path,
                    image=QImage(),
                    display_width=0,
                    display_height=0,
                    error="无法解码该图片",
                    generation=request.generation,
                    prefetch=request.prefetch,
                    cache_bucket=request.bucket,
                    full=request.full,
                )
            else:
                payload = ImagePayload(
                    path=request.path,
                    image=image,
                    display_width=image.width(),
                    display_height=image.height(),
                    taken_at=_read_taken_at(request.path),
                    generation=request.generation,
                    prefetch=request.prefetch,
                    cache_bucket=request.bucket,
                    full=request.full,
                    span=span,
                    source_width=source.width(),
                    source_height=source.height(),
                )
        except Exception as exc:  # noqa: BLE001 - 任务边界必须兜住一切
            get_logger("image").error("解码任务异常 %s：%s", request.path, exc)
            payload = ImagePayload(
                path=request.path,
                image=QImage(),
                display_width=0,
                display_height=0,
                error=str(exc),
                generation=request.generation,
                prefetch=request.prefetch,
                cache_bucket=request.bucket,
                full=request.full,
            )
        self._signals.finished.emit(self.task_id, payload)


class ImageLoader(QObject):
    """解码调度器；对外只暴露请求接口与 ``loaded`` 信号。"""

    loaded = Signal(object)

    def __init__(self, parent: QObject | None = None, budget: int = _CACHE_BUDGET) -> None:
        super().__init__(parent)
        self._logger = get_logger("image")
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(3)
        self._signals = _TaskSignals(self)
        self._signals.finished.connect(self._on_finished)
        self._cache: OrderedDict[tuple[Path, int], ImagePayload] = OrderedDict()
        self._budget = budget
        self._cache_bytes = 0
        self._active: dict[int, _DecodeTask] = {}
        self._task_seq = 0
        self._generation = 0

    # ---------------------------------------------------------------- 对外接口
    def next_generation(self) -> int:
        """递增并返回新的请求代号，用于抢占旧结果。"""
        self._generation += 1
        return self._generation

    @property
    def generation(self) -> int:
        """当前请求代号。"""
        return self._generation

    def request(self, path: Path, target_width: int, generation: int) -> None:
        """请求解码当前图片（优先读缓存）。"""
        bucket = bucket_for(target_width)
        cached = self._cache.get((path, bucket))
        if cached is not None:
            self._cache.move_to_end((path, bucket))
            self.loaded.emit(replace(cached, generation=generation, prefetch=False))
            return
        self._submit(_Request(path, bucket, generation, prefetch=False, full=False))

    def request_full(self, path: Path, generation: int) -> None:
        """请求全分辨率解码（放大查看细节时使用）。"""
        self._submit(_Request(path, 0, generation, prefetch=False, full=True))

    def prefetch(self, paths: list[Path], target_width: int) -> None:
        """预热相邻图片，命中后直接进缓存，不打扰界面。"""
        bucket = bucket_for(target_width)
        for path in paths:
            if (path, bucket) in self._cache:
                continue
            if len(self._active) >= _MAX_PENDING:
                return
            self._submit(_Request(path, bucket, self._generation, prefetch=True, full=False))

    def cached(self, path: Path, target_width: int) -> ImagePayload | None:
        """取缓存中的预览图。"""
        return self._cache.get((path, bucket_for(target_width)))

    def shutdown(self) -> None:
        """退出前等待线程池收尾，避免线程在解释器析构期仍运行。"""
        self._pool.clear()
        self._pool.waitForDone(3000)

    # ----------------------------------------------------------------- 内部实现
    def _submit(self, request: _Request) -> None:
        self._task_seq += 1
        task = _DecodeTask(self._task_seq, request, self._signals)
        self._active[self._task_seq] = task
        self._pool.start(task)

    def _on_finished(self, task_id: int, payload: ImagePayload) -> None:
        task = self._active.pop(task_id, None)
        if task is None:
            return
        image = payload.image
        has_image = isinstance(image, QImage) and not image.isNull()
        if not payload.error and has_image and not payload.full:
            self._remember(payload)
        self.loaded.emit(payload)

    def _remember(self, payload: ImagePayload) -> None:
        image = payload.image
        if not isinstance(image, QImage) or image.isNull():
            return
        key = (payload.path, payload.cache_bucket)
        previous = self._cache.pop(key, None)
        if previous is not None and isinstance(previous.image, QImage):
            self._cache_bytes -= int(previous.image.sizeInBytes())
        self._cache[key] = payload
        self._cache_bytes += int(image.sizeInBytes())
        while self._cache_bytes > self._budget and len(self._cache) > 1:
            _, evicted = self._cache.popitem(last=False)
            if isinstance(evicted.image, QImage):
                self._cache_bytes -= int(evicted.image.sizeInBytes())
