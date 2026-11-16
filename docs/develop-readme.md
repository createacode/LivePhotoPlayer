# 实况照片播放器 v4.8.0 - Copyright © XAF 2026.11

面向开发者的开发手册：环境、构建、调试、架构、性能预算、打包发布与踩坑记录。
项目定位与模块说明见 [readme.md](readme.md)。

## 1. 环境与依赖

### 1.1 基础环境

| 项 | 要求 |
| --- | --- |
| 操作系统 | Windows 10 1809+ / Windows 11 x64（开发与目标机一致） |
| Python | 3.11+，本仓库以 3.13 开发（`.python-version` 固定主次版本） |
| 包管理 | uv（`uv sync --frozen` 可复现） |
| 打包 | PyInstaller 6.22.3（dev 依赖，已锁定） |
| 无外部运行时 | 不需要 VLC、FFmpeg 安装包或任何系统解码器 |

### 1.2 依赖清单

运行时（`[project].dependencies`，全部精确锁定）：

| 包 | 版本 | 用途 |
| --- | --- | --- |
| PySide6-Essentials | 6.12.0 | QtCore / QtGui / QtWidgets / QtNetwork |
| PySide6-Addons | 6.12.0 | QtMultimedia、QtMultimediaWidgets（QtMultimedia 在 Addons 里） |
| pillow | 13.0.0 | EXIF 读取、HEIC 转 JPEG |
| pillow-heif | 1.8.1 | HEIC / HEIF 解码（stock Pillow 不含 libheif） |

关键事实：**QtMultimedia 属于 PySide6-Addons，不属于 Essentials**。若只装 Essentials，
`from PySide6.QtMultimedia import QMediaPlayer` 会失败。不要安装 `PySide6` 元包——它会连带
拉入 WebEngine / Pdf，安装体积从 432MB 涨到 770MB。

### 1.3 安装步骤

```powershell
# 在仓库根目录
uv sync --frozen --extra dev
```

`uv sync` 会创建项目内 `.venv/` 并以可编辑模式安装本包，因此 `import livephoto_player` 可用。

## 2. 构建与配置

### 2.1 常用命令

```powershell
uv run python main.py                      # 开发态启动
uv run python -m livephoto_player          # 等价入口
uv run pytest -q                           # 单元测试
uv run pytest -q --cov --cov-report=term   # 覆盖率
uv run ruff check src tests scripts        # 静态检查
uv run ruff format --check src tests scripts
uv run mypy                                # 类型检查（strict，ui 与 tests 之外）
```

### 2.2 配置项

配置文件：exe 同级 `config/config.json`（不可写时回退 `%LOCALAPPDATA%\LivePhotoPlayer\config`）。

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `schema_version` | 1 | 配置结构版本，加载时自动升级 |
| `last_directory` | `""` | 上次打开的目录 |
| `window_width` / `window_height` | 1080 / 760 | 窗口大小，加载时按屏幕裁剪 |
| `window_x` / `window_y` | `null` | 窗口位置；为 `null` 时居中 |
| `speed_index` | 3 | 播放速度索引（0→0.25x … 6→2x） |
| `muted` | false | 静音 |
| `auto_play` | false | 切换照片即播放实况 |
| `show_file_list` | true | 文件列表是否可见 |
| `log_level` | INFO | 日志级别 |
| `tray_hint_shown` | false | 是否已提示过「关闭到托盘」 |
| `update.owner` / `update.repo` | user_gitee / LivePhotoPlayer | 更新检查仓库 |
| `update.last_check` | `""` | 上次检查时间（24 小时节流） |
| `update.ignored_version` | `""` | 用户忽略的版本 |

写入策略：临时文件 + `Path.replace` 原子替换，写前保留 `config.json.bak`；
解析失败时把坏文件改名为 `config.json.corrupt` 并回退默认值，不崩溃。

### 2.3 产物路径

| 产物 | 路径 |
| --- | --- |
| 版本资源 | `scripts/version_info.txt`（脚本生成，已 gitignore） |
| 打包中间目录 | `build/` |
| 打包输出 | `dist/LivePhotoPlayer/` |
| 发布目录 | `release/LivePhotoPlayer_v{version}_win-x64_{YYYYMMDD}/` |
| 发布 zip | `release/*.zip` |
| 校验和 | 发布目录内 `SHA256SUMS.txt` |

## 3. 调试与测试

### 3.1 日志

- 位置：`logs/log_YYYYMMDD_HHMMSS_NN.log`，单文件上限 10MB，保留最近 30 天或 100 个。
- 崩溃转储：`logs/crash_YYYYMMDD_HHMMSS.log`，由 `faulthandler` 写入。
- Qt / FFmpeg 消息：通过 `qInstallMessageHandler` 汇入同名日志器（`livephoto_player.qt`）。
  排查「视频打不开」时先看这里，FFmpeg 会把流信息与错误原因打出来。

### 3.2 测试

- 框架：pytest + pytest-qt + pytest-cov。
- `tests/conftest.py` 在导入阶段设置 `QT_QPA_PLATFORM=offscreen`，因此测试不会弹窗。
- 覆盖率现状：`core/` 约 94%，`services/` 约 78%（`ui/` 由人工与集成验证覆盖）。
- 测试数据全部由用例现场生成（合成实况照片、Pillow 生成图片），不依赖仓库素材。

### 3.3 命令与验证脚本

```powershell
LivePhotoPlayer.exe --version      # 打印版本与版权
LivePhotoPlayer.exe --help         # 打印用法
LivePhotoPlayer.exe "D:\photo.jpg" # 直接打开某个文件或目录
```

`scripts/capture-window.ps1` 与 `scripts/capture-playback.ps1` 会启动打包产物、
用 `PrintWindow` 截图并模拟回车键，用来确认「界面真的渲染出来」「实况真的能播」。
它们只在 Windows 桌面会话下可用。

### 3.4 性能调试方法

先用离屏平台做功能验证，再在真机平台测时间。二者差异极大，见 §8。

```powershell
# 离屏：验证功能与绘制成本
$env:QT_QPA_PLATFORM = 'offscreen'
uv run python your_probe.py

# 真机：GPU 渲染下的真实首帧与启动时间（窗口可移到屏幕外）
Remove-Item Env:QT_QPA_PLATFORM
```

## 4. 代码与架构

### 4.1 模块职责

| 模块 | 职责 | 不做什么 |
| --- | --- | --- |
| `core/version.py` | 版本、作者、版权年月唯一真源 | 不写第二份版本号 |
| `core/livephoto.py` | 流式定位尾部 MP4（XMP 长度 / `ftyp` 回退） | 不碰 Qt |
| `core/models.py` | `MediaKind`、`VideoSpan`、`MediaItem`、`ImagePayload`、`PlaybackState` | 不含业务逻辑 |
| `core/naming.py` | 导出命名与去重 | 不写文件 |
| `services/browser.py` | 目录扫描、自然排序、mtime 缓存 | 不解码 |
| `services/image_loader.py` | 线程池解码、缩放解码、LRU 缓存、相邻预取、generation 抢占 | 不建控件、不碰 QPixmap |
| `services/tail_device.py` | 把文件区间包装成可寻址 `QIODevice` | 不解析 MP4 |
| `services/media_engine.py` | `QMediaPlayer` 封装、状态机、音频延迟初始化 | 不建 UI |
| `services/exporter.py` | 照片导出、HEIC 转码、区间抽取 | 不弹窗 |
| `services/workers.py` | 通用后台任务（导出、更新检查） | 不阻塞 UI |
| `services/catalog.py` | SQLite 结构化目录：照片元数据、收藏、扫描断点 | 不解析文件 |
| `services/metadata.py` | EXIF 时间 / GPS / 相机 + 文件名时间戳回退 | 只在后台线程调用 |
| `services/indexer.py` | 低优先级、增量、可续扫的索引线程 | 不碰 UI、不弹窗 |
| `services/favorites.py` | 收藏状态与副本文件管理 | 只删自己目录下的副本 |
| `services/geodb.py` | 2889 个区县坐标表 + 1° 网格索引 + 最近点匹配 | 不联网、不解析文件 |
| `services/geocode.py` | 天地图 / Nominatim 反查与响应解析（纯函数可测） | 不内置任何 key |
| `services/place_resolver.py` | 后台补地名，离线即时、在线限速，配额错误自动退避 | 不阻塞 UI |
| `ui/timeline_view.py` | 全屏时间线（竖轴/日期跳转/缩放/长按拖动/精简右键菜单） | 只发意图信号 |
| `ui/preview_window.py` | 无边框预览浮窗（翻页/实况/切回），自带 loader 与播放器 | 关闭即释放 |
| `ui/thumbnails.py` | 缩略图：图片解码 + 视频抓帧排队 + LRU | 不阻塞滚动 |
| `update/gitee.py` | Release API 客户端与版本比较（纯函数） | 不做网络之外的副作用 |
| `update/downloader.py` | 下载、SHA-256 校验、大小核对 | 不安装 |
| `ui/image_canvas.py` | 自绘图片视图：缩放、平移、区域点击、骨架屏 | 不读文件 |
| `ui/video_surface.py` | `QVideoWidget` + 封面覆盖层 | 不控制播放 |
| `ui/file_panel.py` | `QListView` + `QAbstractListModel` | 不重建模型 |
| `ui/main_window.py` | 装配、状态机、菜单、托盘、持久化 | 不做解码 |
| `app/main.py` | 启动顺序、单实例、退出收尾 | 不含业务逻辑 |

### 4.2 线程模型

| 线程 | 承载 | 约束 |
| --- | --- | --- |
| UI 线程 | 所有 QWidget、QPixmap、QMediaPlayer 调用 | 禁止任何文件解码、网络、整图缩放 |
| `QThreadPool`（3 线程） | 图片解码 + 内嵌视频探测 + EXIF | 只产出 `QImage` 与纯数据 |
| `QThreadPool`（2 线程） | 导出、更新检查 | 结果通过信号回 UI |
| `IndexWorker`（1 线程，LowPriority） | 目录索引：stat 比对 + 元数据抽取 | 每文件休眠 6ms，40 条提交一次，写断点 |
| Qt Multimedia 内部线程 | 解复用与解码 | 不直接接触 Python UI 对象 |

跨线程只传 `ImagePayload`（dataclass）与信号；`generation` 单调递增，旧结果到达即丢弃。

### 4.3 性能预算与实测

| 指标 | 预算 | 实测（真机 / 离屏） |
| --- | --- | --- |
| 冷启动到可交互 | < 1.0s | 约 0.6s（导入 0.12s + 界面 0.37s + 首帧 0.16s） |
| 相邻切图 | < 80ms 感知 | 中位 3~5ms（预取命中），最差 190ms（未命中） |
| 绘制一帧（25MP 适应窗口） | < 8ms | 0.96ms |
| 绘制一帧（300% 缩放） | < 8ms | 1.4~1.9ms |
| 滚轮缩放一步 | < 16ms | 1.3~1.5ms |
| 外部视频首帧 | < 300ms | 33ms（选中即预解析） |
| 实况首帧 | < 600ms | 约 500ms（HEVC 首帧解码本身） |
| 连续 60 次快速切图 | 不丢帧、不崩 | 76~120ms 全部走完，最终图正确 |
| 索引吞吐 | 不抢占前台 | 约 160 个文件/秒上限（6ms/文件），17 个文件约 0.2s |
| 索引对首张打开的影响 | 0 | 首张 158~177ms（与引入索引前一致，索引在后台另一线程） |

### 4.4 结构化目录与索引策略

- 存储：SQLite（WAL）。`photos` 每文件一行；`favorites` 记收藏与副本；`scan_state` 记断点。
- 增量：只比对 `size` 与 `mtime`，没变就跳过；文件删除只在整目录扫完后才清理，避免中断误删。
- 续扫：每 20 个文件写一次 `last_path`，下次从其后继续。
- 让路：独立 `QThread` 且 `LowPriority`，每文件 `msleep(6)`，每 40 条提交一次事务。
- 静默：不弹窗、不抢焦点，只有 `directory_done` 信号让主界面悄悄刷新时间线。
- 时间来源优先级：EXIF `DateTimeOriginal` → 文件名时间戳 → 文件修改时间。
  视频没有 EXIF，用文件名（`VID20260809154030`）比文件时间可靠得多。
- 地点：只读 EXIF GPS 并显示坐标，**不做在线反查**，保持"不联网"承诺。

### 4.5 关键实现要点

1. **画布只在必要时重采样**
   - 适应窗口：一次 `QImage.scaled` 后缓存 `QPixmap`，重绘只 `drawPixmap`；
   - 放大：`drawImage(target, image, source)` 配合 `SmoothPixmapTransform`，Qt 只采样可见区域，
     成本与视口像素数相关，**不随原图分辨率增长**；
   - 快速缩放时先用 `FastTransformation`，停止滚动 90ms 后再做一次平滑重采样。
2. **以原图像素为坐标基准**：画布的缩放、平移、矩形全部在"原图像素空间"计算，
   `100%` 恒等于一个原图像素对应一个屏幕像素，与当前解码到多少分辨率无关；
   预览升级到全分辨率时目标矩形不变，画面不会跳变。
3. **解码质量优先**：预览一律"全解码 + 平滑缩放"，**不用**
   `QImageReader.setScaledSize` 作为最终尺寸（Qt 的 JPEG 解码器会走 libjpeg
   非整数比例采样，实测锐度低 20~40%）。只有超过 4000 万像素的超大图才先用
   整数分之一（1/2、1/4）预缩小，再平滑缩放到目标宽度。
4. **两级分辨率**：预览按「视口宽 × DPR × 1.3」解码；当显示尺寸超过可用位图
   10% 时，后台请求全分辨率并原地升级。
5. **零临时文件**：`TailDevice` 把 `[offset, EOF)` 暴露成 `QIODevice`，
   `QMediaPlayer.setSourceDevice` 直接播放。
6. **播放器单例**：全进程一个 `QMediaPlayer`，切图只换 source；`stop()` 仅在确实持有源时调用。
7. **音频延迟**：`QAudioOutput` 在首次打开视频时才创建，避开 Windows 上音频设备枚举的开销。
8. **配置去抖**：窗口尺寸/位置变化后 500ms 才落盘；关闭时强制保存。

## 5. 开发过程

### 5.1 需求拆解

1. 保留 v3 全部用户可见功能（实况播放、缩放平移、列表、导出、托盘、快捷键、拖拽/命令行）。
2. 解决「不丝滑」：定位到渲染、加载、列表、VLC 生命周期、启动打包五类根因。
3. 解决「闪退」：空指针、线程生命周期、跨线程 QPixmap、事件泄漏、退出路径。
4. 满足工程规范：分层、类型、测试、文档、版本单一真源、四脚本、更新检查。

### 5.2 方案选型

| 决策点 | 选项 | 结论 |
| --- | --- | --- |
| GUI 框架 | PyQt5 / PySide6 | PySide6：规范要求、LGPL、Qt6 |
| 播放引擎 | libvlc / Qt Multimedia / mpv | Qt Multimedia：FFmpeg 后端可解 HEVC，零外部运行时 |
| 内嵌视频 | 临时文件 / `QIODevice` | `QIODevice`：省 16MB/次拷贝，无残留 |
| 图片视图 | `QScrollArea` / 自绘 | 自绘：旧方案平移失效 |
| 列表 | `QListWidget` / Model-View | Model-View：不重建、可 `scrollTo` |
| 打包 | onefile / onedir | onedir：首启不解包 |

### 5.3 失败尝试与不推荐做法

- **用 `QMediaPlayer.setSource(file://)` 播内嵌视频**：必须先把尾部抽成临时文件，回到 v3 的老问题。
- **保留 VLC 作为兜底**：本机无 `libvlc.dll` 无法验证，且会让包体积与崩溃面翻倍；已放弃。
- **只装 `PySide6-Essentials`**：`QtMultimedia` 在 Addons，导入直接失败。
- **用 `QVideoSink` 在离屏环境测首帧**：能解码，但每帧 CPU 转换，得出 1s 的错误结论。

## 6. 打包与发布

### 6.1 一键构建

```powershell
pwsh -File scripts/build.ps1
```

脚本按顺序执行并任一步失败即中止：

1. `uv sync --frozen --extra dev`
2. `python scripts/gen_version_info.py`（生成 `scripts/version_info.txt`）
3. `python scripts/sync_version.py`（更新版权年月、`VERSION.txt`、三份文档标题与修订记录）
4. `python scripts/verify_version.py`（不一致直接非零退出）
5. `ruff check` / `ruff format --check` / `mypy` / `pytest`
6. `PyInstaller --onedir --windowed`（带 `--exclude-module` 精简 Qt 模块）
7. 复制 exe 同级 `README.md`、`docs/`、`config/`、`logs/`、`VERSION.txt`、
   `THIRD-PARTY-NOTICES.md`、`LICENSE`、`app.ico`
8. 生成 `SHA256SUMS.txt` 并打 zip

### 6.2 等价的 PyInstaller 命令

```powershell
uv run pyinstaller --noconfirm --clean --onedir --windowed ^
  --name LivePhotoPlayer --icon app.ico ^
  --version-file scripts/version_info.txt ^
  --add-data "app.ico;." --add-data "cover;cover" ^
  main.py
```

`--onedir` 会把 `--add-data` 放进 `_internal/`，因此文档与目录必须由脚本复制到 exe 同级。

### 6.3 版本与版权单一真源

- 唯一真源：`src/livephoto_player/core/version.py` 的 `__version__` / `__author__` /
  `__copyright_ym__` / `__software_name__`。
- `pyproject.toml` 通过 `[tool.hatch.version] path = ...` 动态读取，不写第二份。
- 派生：`scripts/version_info.txt`、`VERSION.txt`、三份文档标题、窗口标题、关于对话框、
  托盘提示、exe 属性。
- 校验：`scripts/verify_version.py`，不一致返回 1。

### 6.4 发布说明要点

- 目标机无需安装 Python，也无需安装 VLC。
- 未签名 exe 可能触发 SmartScreen；给出 `SHA256SUMS.txt` 校验方法。
- 杀毒软件误报时引导用户核对哈希并加白。
- 正式发布建议使用代码签名证书。

## 7. 更新说明（Gitee Release API）

- 接口：`GET https://gitee.com/api/v5/repos/{owner}/{repo}/releases/latest`
- 仓库配置：`config/config.json` 的 `update.owner` / `update.repo`，不散落在代码里。
- 请求：`urllib.request`，`User-Agent: 实况照片播放器/{version}`，只允许 HTTPS，超时 10 秒。
- 比较：去掉 `v` 前缀后按 `MAJOR.MINOR.PATCH` 逐段数值比较；`prerelease` 为真时自动检查不提示。
- 节流：自动检查最多每 24 小时一次，时间写入 `update.last_check`。
- 入口：「关于」对话框与「更多」菜单的「检查更新」。
- 下载：存到 `%TEMP%\LivePhotoPlayer\update`，先按 `assets[].digest` 校验 SHA-256，
  缺失时回退同批 `SHA256SUMS.txt`，并核对 `size`；失败删除文件并提供手动下载。
- 安装：仅打开安装包/便携包，必须用户确认；不以任何方式静默覆盖。
- 手动检查失败会提示；自动检查失败只写日志，不阻塞、不误报「已是最新」。

发布端流程：改版本号 → `sync_version.py` → 打 tag `vX.Y.Z` → Gitee 新建发行版 →
上传 zip 与 `SHA256SUMS.txt` → 回查 `releases/latest`。

## 8. 经验总结

1. **性能问题先用数字定位**，不要凭直觉改。本次最大的两处收益（画布重采样、VLC 重建）
   都是靠实测确认的；而「媒体解析阻塞」在两台设备上结论完全相反。
2. **平台差异必须真机复测**：同一份代码，外部视频首帧在离屏平台 1044ms、真机 33ms。
   离屏没有 RHI，每帧走 CPU 转换，用它评价播放性能会得出错误结论。
3. **缓存必须带完整判定信息**：只缓存图片不缓存 span，就出现了「预取过的实况照片不能播放」。
4. **Qt 的隐式契约要当真**：`QPixmap` 仅 GUI 线程、`QMediaPlayer` 换源要先停、
   `QScrollArea(widgetResizable=True)` 会让滚动条失效。
5. **`setSource(QUrl())` 不是免费的**：空源时停止/清源纯属开销，改为条件调用后首帧明显提前。
6. **单一状态机胜过一堆布尔量**：v3 的 `is_playing` / `video_extracted` / `is_live_photo`
   互相打架，v4 用 `PlaybackState` + `MediaKind` 收口。

## 9. 注意事项

- 不要给 `QApplication` 关闭高 DPI（`AA_DisableHighDpiScaling`），会破坏 4K 屏显示。
- 不要在 `ai` 线程创建 `QPixmap`，也不要在工作线程触碰任何 QWidget。
- 不要把 `QtMultimedia` 当成 Essentials 的一部分。
- 不要在 `closeEvent` 里做耗时释放；统一走 `quit_app()`。
- 不要在文档或代码里写第二处版本号；改版本只改 `core/version.py`。
- `docs/demo/` 是本地测试素材，**不进入发布包**（`build.ps1` 只复制两份 md）；`docs/develop/` 是开发规范参考，同样不随包分发。
- 仓库中残留的 `vlc/` 目录是 v3 的运行时说明与插件精简脚本，v4 不再引用，可自行删除。

## 10. 踩坑记录

| # | 现象 | 原因 | 解决 | 验证 | 如何避免 |
| --- | --- | --- | --- | --- | --- |
| 1 | 缩放后完全拖不动 | `widgetResizable=True` 下 widget 尺寸等于视口，滚动条范围 0 | 自绘画布，自管 `pan` | 实测滚动范围不再恒为 0；300% 可拖到四角 | 需要滚动就自己实现 |
| 2 | 每帧卡顿，图片越大越卡 | `paintEvent` 里对整图 `scaled(Smooth)` | 适应窗口缓存位图；放大用 painter 变换 | 25MP 绘制 0.96ms | 重绘路径里禁止全图重采样 |
| 3 | 预取过的实况照片不能播 | 预取任务不探测 span，缓存 payload 缺 span | 预取也探测并写入缓存 | 14 张样例全部识别 | 缓存内容要与判定逻辑对齐 |
| 4 | 切图偶尔白图 | 工作线程建 `QPixmap` | 线程产出 `QImage` | 60 次切换无白图 | 严守线程边界 |
| 5 | 退出偶发崩溃 | 退出路径新建 VLC 实例且不释放 | 统一 `shutdown()` | 连续 10 次退出无异常 | 退出路径只释放不创建 |
| 6 | 首帧黑屏约 1 秒 | 离屏无 RHI，逐帧 CPU 转换 | 真机复测为 33ms | 真机平台 | 性能结论标注测试平台 |
| 7 | HEIC 全部报「无法显示」 | stock Pillow 无 libheif | 依赖加入 pillow-heif 并注册 opener | `features.check` 与真实 HEIC 解码 | 宣称支持某格式前先实测 |
| 8 | 先装 `PySide6` 体积暴涨 | 元包连带 WebEngine/Pdf | 只装 Essentials + Addons | venv 770MB → 432MB | 精确选择发行包 |
| 9 | `ruff format` 与 `E501` 互相打架 | 格式化会合并长行 | 先 format 再 check，冲突处手动换行 | 两条命令均通过 | 行宽与格式化统一配置 |
| 10 | 照片显示发糊、细节糊成一团 | 预览用 `QImageReader.setScaledSize` 让 libjpeg 做非整数比例采样 | 全解码 + 平滑缩放，只有 >40MP 才整数预缩小 | 拉普拉斯方差 2230→3548、与参考实现 PSNR 99dB | 预览解码必须自己控制最后一次缩放 |
| 11 | 显示"100%"却只有原图 38% 大，且放大后画面突然暴涨 2.6 倍 | 画布几何用"已解码位图尺寸"当基准，全分辨率升级时基准跟着变 | 几何全部改用原图像素，升级只换位图不改矩形 | 100% 精确等于原图宽度、升级前后矩形不变 | 坐标基准必须与"当前解码到多少"解耦 |
| 12 | 打开视频只看到通用封面，认不出是哪个视频 | 封面是固定的 `cover/video.png` | 用独立 `QMediaPlayer + QVideoSink` 抓视频首帧做封面，失败才退回通用图 | 实际抓到 1080×1920 首帧并显示 | 封面应来自内容本身 |
| 19 | 视频行永远显示"载入中…" | 视频不能用 QImageReader 解码 | 用 PosterGrabber 排队抓首帧，抓不到才显示占位 | 时间线里视频有封面 | 视频与图片要走两条缩略图通路 |
| 20 | 时间线按钮点了没反应 | 切换逻辑误调用 `_stop_playback`（实际叫 `stop_playback`），windowed 模式下异常被吞 | 修正方法名 | 模式可正常切换 | windowed 打包要保证异常落盘，否则槽内异常静默 |
| 16 | 批量抓阿里 DataV 行政区划时全部 403 | 短时间 700+ 次请求被 CDN 限流，持续 25 分钟未恢复 | 改用天地图 `/v2/administrative`，按省级 adcode 一次拿整棵子树 | 34 次请求拿到 2889 个区县，198KB | 批量抓公开数据要限速，并准备第二数据源 |
| 17 | 天地图测试 key 返回 HTTP 429 | 免费 key 有并发/每日配额，脚本刚跑过 34 次 | 把源的最小间隔调到 1 秒，429 视为可重试并退避 8 秒 | 解析线程不再把整批标成永久失败 | 配额类错误必须与"数据不存在"区分开 |
| 18 | 离线地名在边境处串到邻县 | 只有中心点没有边界 | 界面标注离线为近似，并提供在线模式 | 城市内 0.4~2.3km 准确，乡村 25~65km 有偏差 | 说法要诚实：近似就不要宣称精确 |
| 13 | 视频在时间线里排到最前面 | 视频没有 EXIF，退回文件修改时间显示成"拷贝时间" | 先解析文件名中的 `YYYYMMDDHHMMSS`，再退回文件时间 | 17 个样例日期全部正确 | 时间来源固定优先级：EXIF > 文件名 > 文件时间 |
| 14 | 索引线程的代码覆盖率始终上不去 | Qt 创建的线程不经过 `threading.settrace`，coverage 采不到 | 接受现状并在文档标注，靠集成验证兜底 | 服务层整体仍 ≥70% | Qt 线程内的覆盖率不可信，别据它判断测试质量 |
| 15 | 关掉软件再打开，索引要重扫 | 没有记录进度 | `scan_state` 存每个目录扫到哪个文件 | 中断后从断点继续 | 长任务必须可续 |
| 中文文档被 `sync_version` 改乱 | 标题正则过宽 | 只匹配首个 `# ` 标题行并带版本段校验 | 重复执行结果稳定 | 脚本要幂等 |

## 11. 运维与排错

| 症状 | 排查顺序 |
| --- | --- |
| 启动即退出 | 看 `logs/` 最新日志；`sys.frozen` 下 `_MEIPASS` 是否包含 `app.ico`、`cover/` |
| 视频打不开 | 日志 `livephoto_player.qt` 里的 FFmpeg 输出；确认文件含 `ftyp`；`core.livephoto` 是否返回 span |
| 界面卡顿 | 确认没有在 UI 线程做 IO；检查是否命中预取（未命中会有一次解码） |
| 配置丢失 | 是否存在 `config.json.corrupt`；目录是否可写；是否发生 `%LOCALAPPDATA%` 回退 |
| 更新检查失败 | 日志中的 HTTP 状态；确认 `update.owner/repo` 正确；24 小时节流是否生效 |
| 退出残留进程 | 是否有未关闭的 `TailDevice`；`quit_app` 是否被绕过 |

回滚：`release/` 与 `dist/` 可直接删除重建；代码回滚到上一个 tag 后重新 `build.ps1` 即可。

## 修订记录

| 日期 | 版本号 | 说明 |
| --- | --- | --- |
| 2026-11-16 | 4.8.0 | 锐化升级为教科书级 USM（Pillow C 实现，r0.8/45%/t2 标准档 +70%，增强档 +190%） |
| 2026-11-16 | 4.7.0 | 由 sync_version.py 同步版本号 |
| 2026-11-15 | 4.6.2 | 线程收尾加固：停止超时不再销毁运行中的 QThread；退出时统一等待线程池 |
| 2026-11-15 | 4.6.1 | 修复状态栏左侧'就绪'被文件名压住：状态标签改固定宽度并显式设置 size policy |
| 2026-11-15 | 4.6.0 | 在线 API 解析的地点改为完整地址（含乡镇/村/方位距离），界面支持两行显示 |
| 2026-11-15 | 4.5.7 | 修复点测试必闪退（QThread 在运行中被回收）；key 申请地址改为 cloudcenter；按官方文档核对 geocoder 接口 |
| 2026-11-15 | 4.5.6 | 修复地点解析设置单选框无选中态（选中了看不出），补上 checked 样式；新增 --geo 调试入口与截图脚本 |
| 2026-11-15 | 4.5.5 | 清理遗留文件：删除 vlc/ 与 third_party/ 目录、构建缓存与本地产物；收藏目录加入 .gitignore |
| 2026-11-15 | 4.5.4 | 修复时间线只能停在第一张：程序化切换时屏蔽滚动吸附，滚轮改以当前展开行为基准 |
| 2026-11-15 | 4.5.3 | 列表选中底色只画在照片行上，日期分组标题不再跟着变蓝 |
| 2026-11-15 | 4.5.2 | 区域光标去掉圆底，只保留白色 ‹ › / ▶ / ⏸ 符号（淡描边保证可见），更简约 |
| 2026-11-15 | 4.5.1 | 区域光标改为自绘圆形+白色 ‹ › / ▶ / ⏸，更大更清晰且不再是黑色；实况播放中中间光标自动变暂停 |
| 2026-11-15 | 4.5.0 | 时间线照片上下左右绝对居中（展开项滚到视口正中）；鼠标悬停到左右区变为箭头光标、中间变为播放/暂停光标（图片与视频都生效） |
| 2026-11-15 | 4.4.1 | 照片在内容区真正居中；折叠行只留时间地点更易拖动；支持拖拽文件/文件夹打开；视频支持左右点击切换；星标移到文件名后；到最后一张只提示不跳文件夹 |
| 2026-11-15 | 4.4.0 | 时间线改为滑轮式：仅当前项展开大图、其余折叠成一行；照片只在扣除文字栏的区域内居中不再重叠；区域单击恢复即时响应并去掉双击放大（保留双击还原） |
| 2026-11-15 | 4.3.8 | 区域单击延后到双击判定之后，双击放大不再误触翻页；时间线照片上下居中、文字默认右侧并避让到左侧、时间列更紧凑 |
| 2026-11-15 | 4.3.7 | 时间线照片居中、文字固定右侧独立层（过大时悬浮并加半透明底）；状态栏就绪不再被挤、时间地点区域加宽；列表默认更窄；滚动改按整项并加快吸附 |
| 2026-11-15 | 4.3.6 | 修复列表行高未计入日期标题导致疏密不均；时间线文字移入右侧独立栏、照片可更大且可缩到很小；日历有照片的日期高亮且周末不高亮；预览关闭只关浮层 |
| 2026-11-15 | 4.3.5 | 修复列表时间重复绘制；时间线滚轮一格走一张、拖动自动吸附到整张照片 |
| 2026-11-15 | 4.3.4 | 时间线每节高度限制在视口 52%、增加节间分隔线；预览改回双击；修复预览关闭按钮被全局内边距挤掉 |
| 2026-11-15 | 4.3.3 | 时间线改为竖轴日记式版式：照片居中且不再有卡片包裹，时间/地点/文件名各自独立；修复行高不一致导致的照片重叠；照片上限提升到 920x560 |
| 2026-11-15 | 4.3.2 | 时间线去蓝色填充、文字在左照片在右、单击即预览、日历改独立对话框；列表支持文件夹进入并按拍摄时间分组显示；修复退出时间线后列表不恢复 |
| 2026-11-15 | 4.3.1 | 时间线照片改为按原始比例独立呈现（横竖不挤压、文字为照片让路）；预览改为父窗口内浮层；修复地点解析设置点不动 |
| 2026-11-15 | 4.3.0 | 时间线改为全屏独立界面（竖轴大图/日期跳转/缩放/长按拖动/精简右键菜单）；新增预览浮窗；视频读 MP4 坐标并抓首帧做封面 |
| 2026-11-15 | 4.2.1 | 时间线独立模式（竖轴/按天分区/时间-缩略图-地点）、排序改左右标签、状态栏重排（去相机、地点完整、大小像素置后）、修复右键菜单位置偏移、星标图标重绘 |
| 2026-11-15 | 4.2.0 | 新增地点解析：默认内置 2889 区县离线表（不联网），可选天地图/OSM 在线反查；时间线显示地名 |
| 2026-11-15 | 4.1.0 | 新增收藏与两个时间线标签、主界面拍摄时间线、全库搜索；引入 SQLite 结构化索引（后台静默、增量、可续扫） |
| 2026-11-15 | 4.0.1 | 修复照片预览发糊、"100%"缩放基准错误与升级跳变；视频改用自身首帧作封面 |
| 2026-11-15 | 4.0.0 | 新建开发手册：环境、构建、架构、性能预算、打包发布、踩坑与排错 |
