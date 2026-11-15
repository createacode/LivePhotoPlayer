"""播放引擎：封装 Qt6 Multimedia（FFmpeg 后端）。

相比 v3 的 libvlc 方案：
- 不再需要 50MB 的 VLC 运行时，也不需要把窗口句柄交给外部库；
- 实况照片的内嵌视频通过 ``TailDevice`` 直接播放，**不产生临时文件**；
- 全进程只有一个 ``QMediaPlayer``，切图只换 source，不存在实例重建与事件泄漏。
"""

from __future__ import annotations

from collections import deque
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer

from livephoto_player.core.models import PlaybackState, VideoSpan
from livephoto_player.services.tail_device import TailDevice
from livephoto_player.utils.logger import get_logger

_EMBEDDED_URL = "livephoto-embedded.mp4"
_RETIRED_LIMIT = 4


class MediaEngine(QObject):
    """对外只暴露与业务相关的最小接口，内部状态一律收敛到 ``PlaybackState``。"""

    state_changed = Signal(object)
    duration_changed = Signal(int)
    position_changed = Signal(int)
    error_occurred = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._logger = get_logger("media")
        self._player = QMediaPlayer(self)
        self._audio: QAudioOutput | None = None
        self._device: TailDevice | None = None
        self._retired: deque[TailDevice] = deque()
        self._state = PlaybackState.IDLE
        self._has_source = False
        self._rate = 1.0
        self._muted = False
        self._audio_checked = False

        self._player.playbackStateChanged.connect(self._refresh_state)
        self._player.mediaStatusChanged.connect(self._refresh_state)
        self._player.errorOccurred.connect(self._on_error)
        self._player.durationChanged.connect(self._on_duration)
        self._player.positionChanged.connect(self.position_changed.emit)

    # ---------------------------------------------------------------- 只读属性
    @property
    def state(self) -> PlaybackState:
        """当前播放状态。"""
        return self._state

    @property
    def duration(self) -> int:
        """媒体总时长（毫秒）。"""
        return int(self._player.duration())

    @property
    def position(self) -> int:
        """当前播放位置（毫秒）。"""
        return int(self._player.position())

    @property
    def rate(self) -> float:
        """当前播放速度倍率。"""
        return self._rate

    @property
    def is_playing(self) -> bool:
        """是否正在播放。"""
        return self._state is PlaybackState.PLAYING

    # ---------------------------------------------------------------- 装配/释放
    def attach_video_output(self, target: QObject) -> None:
        """把画面输出挂到 QVideoWidget 之类的目标上。"""
        self._player.setVideoOutput(target)

    def _ensure_audio(self) -> None:
        """按需创建音频输出。

        Windows 上枚举音频设备可能耗时上百毫秒，放在首次播放时做，
        启动路径就不会被它拖慢。
        """
        if self._audio_checked:
            return
        self._audio_checked = True
        devices = QMediaDevices.audioOutputs()
        if not devices:
            self._logger.warning("未检测到音频输出设备，播放将无声音")
            return
        self._audio = QAudioOutput(self)
        self._audio.setMuted(self._muted)
        self._player.setAudioOutput(self._audio)

    def open_path(self, path: Path) -> None:
        """打开一个独立视频文件。"""
        self._ensure_audio()
        self._prepare_for_new_source()
        self._player.setSource(QUrl.fromLocalFile(str(path)))
        self._has_source = True
        self._logger.debug("打开视频文件：%s", path)

    def open_span(self, path: Path, span: VideoSpan) -> None:
        """打开照片尾部内嵌的视频区间，不落地临时文件。"""
        self._ensure_audio()
        self._prepare_for_new_source()
        device = TailDevice(path, span)
        self._device = device
        self._has_source = True
        self._player.setSourceDevice(device, QUrl(_EMBEDDED_URL))
        self._logger.debug("打开内嵌视频：%s @%s+%s", path, span.offset, span.length)

    def clear(self) -> None:
        """清空当前媒体并让播放器释放文件句柄。"""
        self._prepare_for_new_source()
        try:
            self._player.setSource(QUrl())
        except Exception as exc:  # noqa: BLE001 - 释放失败不应中断流程
            self._logger.warning("清空播放源异常：%s", exc)
        self._state = PlaybackState.IDLE
        self.state_changed.emit(self._state)

    # ---------------------------------------------------------------- 播放控制
    def play(self) -> None:
        """开始或继续播放；播放结束后再次播放会从头开始。"""
        if not self._has_source:
            return
        if self._state in (PlaybackState.ENDED, PlaybackState.STOPPED):
            self._player.setPosition(0)
        self._player.play()

    def pause(self) -> None:
        """暂停播放。"""
        if self.is_playing:
            self._player.pause()

    def toggle(self) -> None:
        """在播放与暂停之间切换。"""
        if self.is_playing:
            self.pause()
        else:
            self.play()

    def stop(self) -> None:
        """停止播放并回到起点。"""
        self._player.stop()
        self._player.setPosition(0)

    def seek(self, position: int) -> None:
        """跳转到指定毫秒位置。"""
        self._player.setPosition(max(0, position))

    def set_rate(self, rate: float) -> None:
        """设置播放速度倍率。"""
        self._rate = max(0.1, min(4.0, rate))
        self._player.setPlaybackRate(self._rate)

    def set_muted(self, muted: bool) -> None:
        """设置静音。"""
        self._muted = muted
        if self._audio is not None:
            self._audio.setMuted(muted)

    def shutdown(self) -> None:
        """退出前释放播放器与所有设备。"""
        try:
            self._player.stop()
            self._player.setSource(QUrl())
            self._player.setVideoOutput(None)  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001 - 退出路径不允许抛异常
            self._logger.warning("关闭播放器时异常：%s", exc)
        self._device = None
        while self._retired:
            self._close_device(self._retired.popleft())

    # ----------------------------------------------------------------- 内部实现
    def _prepare_for_new_source(self) -> None:
        """切换到新媒体前的收尾：停止播放、回收上一个内嵌设备。

        只有在确实持有播放源时才调用 ``stop()``——空源时停止是纯开销，
        而这里正是外部视频首帧延迟的主要来源之一。
        """
        if not self._has_source and self._device is None:
            return
        try:
            self._player.stop()
        except Exception as exc:  # noqa: BLE001 - 停止失败不应中断流程
            self._logger.warning("停止播放异常：%s", exc)
        if self._device is not None:
            self._retired.append(self._device)
            self._device = None
        while len(self._retired) > _RETIRED_LIMIT:
            self._close_device(self._retired.popleft())
        self._has_source = False

    @staticmethod
    def _close_device(device: TailDevice) -> None:
        try:
            device.close()
        except Exception:  # noqa: BLE001 - 句柄关闭失败无需上报
            return

    def _on_duration(self, duration: int) -> None:
        self.duration_changed.emit(int(duration))

    def _on_error(self, _error: QMediaPlayer.Error, message: str) -> None:
        self._logger.error("播放错误：%s", message)
        self._state = PlaybackState.ERROR
        self.state_changed.emit(self._state)
        self.error_occurred.emit(message or "视频解码失败")

    def _refresh_state(self, *_args: object) -> None:
        status = self._player.mediaStatus()
        playback = self._player.playbackState()
        if status == QMediaPlayer.MediaStatus.InvalidMedia:
            new_state = PlaybackState.ERROR
        elif status == QMediaPlayer.MediaStatus.EndOfMedia:
            new_state = PlaybackState.ENDED
        elif playback == QMediaPlayer.PlaybackState.PlayingState:
            new_state = PlaybackState.PLAYING
        elif playback == QMediaPlayer.PlaybackState.PausedState:
            new_state = PlaybackState.PAUSED
        elif status in (
            QMediaPlayer.MediaStatus.LoadingMedia,
            QMediaPlayer.MediaStatus.BufferingMedia,
            QMediaPlayer.MediaStatus.StalledMedia,
        ):
            new_state = PlaybackState.LOADING
        elif playback == QMediaPlayer.PlaybackState.StoppedState:
            new_state = PlaybackState.STOPPED if self._has_source else PlaybackState.IDLE
        else:
            new_state = PlaybackState.IDLE
        if new_state is not self._state:
            self._state = new_state
            self.state_changed.emit(new_state)

    def __del__(self) -> None:
        # 解释器退出阶段不再依赖 Qt 事件循环，直接确保设备句柄被释放。
        while getattr(self, "_retired", None):
            device = self._retired.popleft()
            try:
                device.close()
            except Exception:  # noqa: BLE001 - 析构期不再上报
                break
