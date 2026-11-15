# 实况照片播放器 v4.6.2 - Copyright © XAF 2026.11

面向开发者的项目说明书。构建、测试、打包与发布步骤见 [develop-readme.md](develop-readme.md)；
面向使用者的产品介绍见根目录 [README.md](../README.md)。

## 1. 项目介绍

### 1.1 定位

一款 Windows 桌面端的**实况照片（Live Photo）查看与导出工具**。核心能力是把手机照片
尾部内嵌的 MP4 视频识别出来，并让「照片」与「视频」在同一界面里无缝切换。

### 1.2 背景

OPPO 系（含一加、realme）与 Google 的运动照片把视频直接拼在 JPEG 尾部：

```
[JPEG 图像数据 ... XMP 元数据][内嵌 MP4 (ftyp + mdat + moov)]
```

操作系统与常见看图软件只会把它当作一张 JPG，视频部分不可见。v3 采用「提取到临时文件
再交给 libvlc 播放」的方式，带来三个问题：临时文件堆积、每次切图重建播放器、50MB 运行时
导致启动缓慢。

v4 改用 **Qt6 Multimedia 的 FFmpeg 后端 + 自定义 `QIODevice`**，让播放器直接从照片尾部读取
字节，彻底消除了临时文件与运行时依赖。

### 1.3 目标用户

- 用手机拍实况照片、需要在 Windows 上快速浏览的人；
- 需要把实况照片里的视频单独导出成 MP4 的人。

### 1.4 目标 / 非目标

| 目标 | 非目标 |
| --- | --- |
| 秒开、翻页无卡顿、缩放拖动顺滑 | 照片修图、滤镜、裁剪 |
| 播放稳定不闪退，异常有日志可查 | 视频剪辑、转码、合并 |
| 识别多种厂商的内嵌视频格式 | 云同步、账号体系 |
| 单文件配置、绿色免安装 | 支持 macOS / Linux |

## 2. 项目概况

- 当前版本：4.0.0
- 技术栈：Python 3.11+ / PySide6 6.12（Qt 6.12）/ Pillow / pillow-heif
- 打包：PyInstaller 6.22（`--onedir --windowed`）
- 状态：功能完整，静态检查与单元测试通过；发行包由 `scripts/build.ps1` 一键产出

### 2.1 目录结构

```text
LivePhotoPlayer/
├─ main.py                     # 薄入口，调用 livephoto_player.app.main:main
├─ pyproject.toml / uv.lock / .python-version
├─ app.ico                     # exe / 窗口 / 托盘 / 关于对话框统一图标
├─ cover/video.png             # 外部视频封面
├─ src/livephoto_player/
│  ├─ app/                     # 入口与单实例
│  ├─ core/                    # 版本真源、领域模型、实况解析、导出命名
│  ├─ services/                # 目录浏览、解码、播放引擎、导出、后台任务
│  ├─ ui/                      # 画布、播放区、列表、主窗口、提示、对话框、主题
│  ├─ update/                  # Gitee 发行版检查与下载校验
│  └─ utils/                   # 路径、日志、配置
├─ tests/                      # pytest 用例
├─ scripts/                    # 构建与版本同步脚本
├─ docs/                       # 本文件与开发手册
├─ config/ logs/ third_party/  # 运行期目录（含 .gitkeep）
└─ VERSION.txt
```

### 2.2 分层与职责

| 层 | 模块 | 职责 | 依赖方向 |
| --- | --- | --- | --- |
| 入口 | `app.main` | 日志/异常钩子、QApplication、单实例、窗口生命周期 | 依赖 ui / utils |
| 界面 | `ui.*` | 只做呈现与交互，不直接读文件、不解码、不联网 | 依赖 services / core |
| 服务 | `services.*` | 解码、播放、导出、目录扫描、后台任务、**结构化目录与索引** | 依赖 core |
| 领域 | `core.*` | 纯逻辑：版本、模型、内嵌视频定位、命名规则、时间/地点格式化（无 Qt 依赖） | 无 |
| 数据 | `services.catalog` / `services.indexer` | SQLite 结构化目录 + 低优先级可续扫索引线程 | 依赖 core |
| 基础设施 | `utils.*` | 路径解析、日志、配置 | 无 |

`core` 与 `utils` 不导入 Qt，因此可以脱离 GUI 单元测试；这也是覆盖率的主要来源。

### 2.3 关键数据流

**打开一张实况照片**

```text
MainWindow.open_path
  └─ DirectoryBrowser.scan(directory)           # mtime 缓存，避免重复扫描
  └─ ImageLoader.request(path, target_width, generation)
        └─ QThreadPool 任务
              ├─ QImageReader.setScaledSize(...)  # 按屏宽缩放解码
              ├─ livephoto.find_video_span(...)  # 定位尾部 MP4 区间
              └─ Pillow 读取 EXIF 拍摄时间
  └─ 回到 UI 线程：ImagePayload -> ImageCanvas.set_image
```

**播放内嵌视频**

```text
ImageCanvas.sig_play -> MainWindow.toggle_playback
  └─ MediaEngine.open_span(path, span)
        └─ TailDevice(path, span)                 # QIODevice 视图
        └─ QMediaPlayer.setSourceDevice(device)   # 不写临时文件
  └─ QMediaPlayer.play() -> QVideoWidget
```

**后台结构化索引**

```text
MainWindow._rebuild_session
  └─ 目录扫描 -> MediaItem（先用文件时间占位）
  └─ Catalog.by_paths(..)        # 已索引的记录用来补齐拍摄时间/地点/相机
  └─ IndexWorker.enqueue(dir)    # 交给低优先级线程慢慢补

IndexWorker(QThread, LowPriority)
  └─ 逐文件 stat 比对 (size, mtime) -> 只处理新增/变化的
  └─ read_metadata（EXIF 时间、GPS、相机；视频回退文件名时间戳）
  └─ 每 40 条提交一次事务 + 每 20 个文件写一次断点
  └─ directory_done -> 主界面悄悄刷新时间线
```

### 2.4 结构化目录（SQLite）

数据库：`%LOCALAPPDATA%\LivePhotoPlayer\cache\catalog.db`（WAL 模式）。

| 表 | 用途 |
| --- | --- |
| `photos` | 每个文件的拍摄时间、`taken_day`、GPS、相机、像素尺寸、类型 |
| `favorites` | 收藏路径、收藏时刻、副本路径、拍摄时刻 |
| `scan_state` | 每个目录扫到哪个文件（断点续扫） |
| `meta` | schema 版本 |

搜索用 `LIKE` 覆盖文件名/地名/相机/目录/日期五个字段，按时间倒序返回。
为什么不用 FTS5：中文没有空格分词，`LIKE '%关键词%'` 对中文子串反而更准；
个人图库量级（万级）下延迟可以忽略。

### 2.5 关键接口

| 接口 | 签名 | 说明 |
| --- | --- | --- |
| `find_video_span` | `(Path) -> VideoSpan \| None` | 流式定位内嵌视频区间；普通照片返回 `None` |
| `ImageLoader.request` | `(Path, int, int) -> None` | 提交解码；`generation` 用于抢占旧结果 |
| `MediaEngine.open_span` | `(Path, VideoSpan) -> None` | 以设备方式打开内嵌视频 |
| `MediaEngine.open_path` | `(Path) -> None` | 打开独立视频文件 |
| `ConfigStore.load/save` | `() -> AppConfig` / `(AppConfig) -> bool` | 原子读写、损坏自愈 |
| `gitee.fetch_latest` | `(owner, repo, *, opener=None) -> UpdateInfo` | 检查更新，异常统一为 `UpdateError` |
| `Catalog.search` | `(query, limit=500) -> list[PhotoRecord]` | 全库搜索，按时间倒序 |
| `Catalog.list_favorites` | `(order) -> list[FavoriteRecord]` | 收藏时间线 / 拍摄时间线 |
| `FavoritesService.toggle` | `(path, taken_ts) -> bool` | 收藏/取消收藏并维护副本文件 |
| `IndexWorker.enqueue` | `(directory) -> None` | 目录入队，后台增量索引 |
| `GeoDB.lookup` | `(lat, lon) -> PlaceName \| None` | 离线查最近区县（返回距离供判断可信度） |
| `reverse_geocode` | `(lat, lon, *, provider, key) -> PlaceName` | 在线反查，异常统一为 `GeocodeError` |
| `PlaceResolver.configure` | `(mode, provider, key) -> None` | 切换地点解析方式并唤醒后台线程 |

### 2.5 运行期目录

| 目录 | 位置 | 回退 |
| --- | --- | --- |
| 配置 | exe 同级 `config/config.json` | `%LOCALAPPDATA%\LivePhotoPlayer\config` |
| 日志 | exe 同级 `logs/log_YYYYMMDD_HHMMSS_NN.log` | `%LOCALAPPDATA%\LivePhotoPlayer\logs` |
| 缓存 | `%LOCALAPPDATA%\LivePhotoPlayer\cache` | exe 同级 `cache` |
| 导出 | exe 同级 `照片/`、`视频/` | `%LOCALAPPDATA%\LivePhotoPlayer\照片`、`\视频` |

## 3. 使用方法（开发向）

```powershell
uv sync --frozen --extra dev      # 安装依赖
uv run python main.py             # 启动
uv run python -m livephoto_player # 等价入口
uv run pytest -q                  # 测试
uv run ruff check src tests scripts
uv run mypy
```

详细构建与发布步骤见 [develop-readme.md](develop-readme.md)。

## 4. 更新记录

| 日期 | 版本 | 变更 |
| --- | --- | --- |
| 2026-11-15 | 4.0.0 | 重写为 PySide6 + Qt6；播放引擎由 libvlc 迁移到 Qt Multimedia；修复 40 余项性能与稳定性问题 |
| 2026-05-02 | 3.18.0 | 修复自动播放黑屏，移除位置记忆 |
| 2026-05-01 | 3.0.0 | 视频封面、自动播放、异步停止 |
| 2026-04-30 | 2.0.0 | 文件列表、导出、配置记忆 |
| 2026-04-30 | 1.0.0 | 初始版本 |

## 5. 项目日志（重要决策）

| 日期 | 决策 | 理由 |
| --- | --- | --- |
| 2026-11-15 | 用 PySide6 替代 PyQt5 | 规范要求；LGPL 更利于分发；Qt6 高 DPI 与渲染更现代 |
| 2026-11-15 | 用 Qt Multimedia 替代 libvlc | 移除 50MB 运行时与 `set_hwnd` 嵌入，消除一类崩溃；FFmpeg 后端可解 HEVC |
| 2026-11-15 | 用 `QIODevice` 直接播放照片尾部 | 取消临时文件，省掉每次切图 16MB 的拷贝 |
| 2026-11-15 | `--onedir` 替代 `--onefile` | onefile 每次启动解包 50MB，是旧版启动慢的主因 |
| 2026-11-15 | 画布改自绘，弃用 `QScrollArea` | 旧方案滚动范围恒为 0，导致缩放后无法平移 |
| 2026-11-15 | 列表改 Model/View | 旧方案每次切图重建 QListWidget，且滚动位置丢失 |

## 6. 问题与踩坑

| 现象 | 影响 | 根因 | 处理 | 验证 | 预防 |
| --- | --- | --- | --- | --- | --- |
| 缩放后拖不动、只能看中心 | 功能不可用 | `QScrollArea` 的 `widgetResizable=True` 让 widget 恒等于视口，滚动范围 0 | 改为自绘画布，自管 `zoom` 与 `pan` | 实测滚动范围不再为 0，300% 缩放可拖到边缘 | 需要滚动时不要让 widget 与视口同尺寸 |
| 预取后实况照片被当成普通照片 | 视频播不出来 | 预取任务跳过 span 探测，缓存命中时 payload 里没有 span | 预取同样探测 span | 14 张样例全部识别为实况 | 缓存必须携带完整的判定信息 |
| 切图偶发白图 | 观感差 | v3 在工作线程创建 `QPixmap` | 工作线程只产出 `QImage`，UI 线程再转 `QPixmap` | 连续 60 次切换无白图 | QPixmap 只能在 GUI 线程使用 |
| 退出偶发崩溃 | 闪退 | v3 在 `quit_app` 里新建 VLC 实例且从不 release | 统一 `shutdown()` 路径，先 stop→release 再退出 | 反复退出 10 次无异常 | 退出路径不允许创建新资源 |
| 视频没有地点 | 视频行显示"地点未知" | 视频没有 EXIF，GPS 藏在 MP4 的 `©xyz` 原子（ISO-6709） | 解析 `©xyz` 得到坐标再离线查表 | 3 段视频全部拿到区县 | 视频与照片的元数据位置完全不同，别用同一套 |
| 离线地名偶尔串到邻县 | 地点显示不准 | 只有区县中心点、没有边界多边形，按最近中心点匹配时，距离中心 25~65km 的乡村点会落到隔壁县 | 保留"省 市 区县"结果并在界面标注离线为近似；提供在线模式做精确反查 | 对比天地图：城市内 0.4~2.3km 准确，乡村 25~65km 时 4 个点中 2 个偏差 | 中心点匹配只能做近似，精确需要边界数据或在线服务 |
| 视频时间线错乱 | 视频排到最前 | 视频没有 EXIF，退回文件修改时间会显示成"拷贝进来的时间" | 优先解析文件名里的 `YYYYMMDDHHMMSS` | 17 个样例时间全部正确 | 时间来源要有优先级：EXIF > 文件名 > 文件时间 |
| 照片发糊 | 观感差 | 预览解码交给 libjpeg 做非整数比例采样，锐度损失 20~40% | 改为全解码 + 平滑缩放 | 与参考实现 PSNR 99dB | 预览解码的最后一次缩放必须自己控制 |
| "100%"名不副实、放大后跳变 | 比例失真 | 画布几何以已解码位图为基准 | 改为以原图像素为基准 | 100% 精确等于原图宽度 | 几何坐标与解码分辨率解耦 |
| 首帧黑屏 1 秒 | 以为卡死 | 离屏软件渲染下 QVideoWidget 每帧 CPU 转换 | 真机 D3D 渲染下首帧 33ms，属测试环境限制 | 真机平台实测 | 性能结论必须在真机平台复测 |

## 7. 注意事项

- **兼容性**：Qt 6 不支持 Windows 7 / 8；最低 Windows 10 1809。
- **权限**：不请求管理员权限；若安装到 `Program Files` 且无写权限，配置与日志会自动回退到 `%LOCALAPPDATA%` 并提示。
- **数据存储**：不写注册表（`QSettings` 未使用）；配置损坏时保留为 `config.json.corrupt` 并回退默认值。
- **安全**：更新检查仅访问 Gitee HTTPS 接口；下载包必须通过 SHA-256 校验；更新说明以纯文本渲染，不执行其中的 HTML。
- **升级 / 回滚**：覆盖 exe 所在目录即可升级，配置兼容（带 `schema_version` 迁移）；回滚到旧版只需恢复旧目录。

## 8. 已知限制

- 实况视频识别依赖 XMP 长度或 `ftyp` 回退，极端定制的拼接格式可能识别失败（会按普通照片展示）。
- 相册列表按目录平铺，不支持多文件夹聚合或收藏夹。
- 不含图片编辑能力。

## 修订记录

| 日期 | 版本号 | 说明 |
| --- | --- | --- |
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
| 2026-11-15 | 4.0.0 | 重写项目说明书，补充分层、数据流、决策与踩坑记录 |
