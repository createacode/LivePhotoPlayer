# 第三方组件声明 - Copyright © XAF 2026.11

本软件在运行时使用以下第三方组件。各组件的版权归其各自作者所有，
本软件仅以未修改的动态库或库调用方式使用它们。

## 运行时依赖

### Qt 6 / PySide6

- 组件：Qt 6.12.0（QtCore、QtGui、QtWidgets、QtMultimedia、QtMultimediaWidgets、QtNetwork）
- 许可：LGPL-3.0（另有商业许可可选）
- 用途：图形界面、图像渲染、视频播放（FFmpeg 后端）、本地单实例通信
- 获取方式：<https://pypi.org/project/PySide6/> 或 <https://www.qt.io/>
- 说明：按 LGPL 要求以动态链接方式使用 Qt。用户可自行替换发行包 `_internal/PySide6` 目录下的
  Qt 动态库为本机编译的同版本库；替换后本软件的其余部分仍可正常运行。
  Qt 源码可从 <https://download.qt.io/official_releases/qt/> 获取。

### Shiboken6

- 组件：Shiboken6 6.12.0
- 许可：LGPL-3.0 / GPL-3.0
- 用途：PySide6 的 C++ 绑定层
- 获取方式：<https://pypi.org/project/shiboken6/>

### FFmpeg（随 Qt Multimedia 插件分发）

- 组件：Qt 6.12 自带的 ffmpeg 媒体后端（FFmpeg 9.0.1 运行库）
- 许可：LGPL-2.1-or-later
- 用途：视频解码与解复用（H.264 / HEVC / AAC 等）
- 获取方式：随 PySide6 发行包一同分发，位于 `_internal/PySide6/` 下的 `avcodec-*` 等动态库
- 说明：以动态库方式使用，未修改其源码。

### Pillow

- 组件：Pillow 13.0.0
- 许可：MIT-CMU（HPND）
- 用途：读取图片 EXIF 拍摄时间；HEIC 转 JPEG 导出
- 获取方式：<https://pypi.org/project/pillow/>

### pillow-heif

- 组件：pillow-heif 1.8.1（内含 libheif）
- 许可：BSD-3-Clause（pillow-heif）、LGPL-3.0（libheif）
- 用途：解码 iPhone / Android 拍摄的 HEIC / HEIF 照片
- 获取方式：<https://pypi.org/project/pillow-heif/>

## 构建期依赖（不随产品分发）

| 组件 | 版本 | 许可 | 用途 |
| --- | --- | --- | --- |
| PyInstaller | 6.22.3 | GPL-2.0-or-later（含例外条款） | 打包为 Windows 可执行程序 |
| pytest | 9.2.0 | MIT | 单元测试 |
| pytest-qt | 4.5.0 | MIT | GUI 相关测试夹具 |
| pytest-cov | 7.1.0 | MIT | 覆盖率统计 |
| ruff | 0.17.5 | MIT | 代码检查与格式化 |
| mypy | 2.4.1 | MIT | 静态类型检查 |

## 地理数据

### 内置区县坐标表（`src/livephoto_player/resources/china_districts.json`）

- 内容：2889 个区县的名称、所属省市、中心点经纬度
- 来源：**天地图行政区划接口** `/v2/administrative` 采集整理（见 `scripts/build_geo_dataset.py`）
- 许可：天地图开放平台服务条款；本文件仅包含行政区划名称与坐标，随本软件一同分发
- 用途：离线把照片 GPS 换算成"省 市 区县"，不联网

### 在线地名反查（可选，默认关闭）

- **天地图**（<https://www.tianditu.gov.cn>）：需用户自行申请 key，本仓库不内置任何 key
- **OpenStreetMap Nominatim**（<https://nominatim.openstreetmap.org>）：免 key，遵守其每秒 1 次的使用政策
- 只有用户主动开启在线模式时才会请求；查询结果缓存在本机 `catalog.db`

## 图标与素材

- `app.ico`、`cover/video.png`：由本项目作者提供，随本软件一同分发。
- `docs/demo/` 下的示例照片与视频仅用于本机测试，**不进入发布包**。

## 许可声明

本软件自身代码的版权归 XAF 所有。上述第三方组件遵循各自的许可协议；
分发本软件时不得移除本文件及 Qt 的许可声明。

---

## 修订记录

| 日期 | 版本号 | 说明 |
| --- | --- | --- |
| 2026-11-15 | 4.0.0 | 从 libvlc 迁移到 Qt6 FFmpeg 后端，重写第三方组件清单 |
