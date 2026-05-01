#  LivePhotoPlayer

A lightweight video playback application powered by VLC libraries.
基于 VLC 库的轻量级视频播放应用程序。

---

### ️ Dependencies / 依赖说明

This software relies on the **VLC media player** components to function. Please ensure you have downloaded the necessary files before running the application.

本软件依赖 **VLC media player** 组件才能运行。请在运行程序前确保已下载必要的文件。

#### Download Options / 下载方式

You can obtain the VLC components from the following sources:
您可以通过以下途径获取 VLC 组件：

- **Official Website / 官方网站:**
  [Download VLC for Windows](https://www.videolan.org/vlc/download-windows.html)
- **Releases Page / Releases 页面:**

  Check the repository's "Releases" section for pre-packaged dependencies.
  请查看本仓库的 "Releases" 页面以获取打包好的依赖文件。
  
  ↓↓↓
  
  [VLC组件下载地址](https://github.com/createacode/LivePhotoPlayer/releases/download/V3.18.0/vlc_up.zip)

> **️ Important / 重要提示:**
> After downloading, ensure the `libvlc.dll`, `libvlccore.dll`, and the `plugins` folder are placed in the correct directory structure as shown below.
> 下载后，请确保将 `libvlc.dll`、`libvlccore.dll` 和 `plugins` 文件夹按照下图所示的目录结构放置。

---

###  File Structure / 文件目录结构

Please maintain the following file structure for the application to work correctly:
为了保证软件正常运行，请保持以下文件目录结构：

```text
├─vlc/
│  ├─plugins/           # VLC plugin modules / VLC 插件模块
│  ├─libvlc.dll         # Core VLC library / VLC 核心库
│  └─libvlccore.dll     # Core VLC library / VLC 核心库
├─App13324.spec         # PyInstaller spec file / PyInstaller 配置文件
├─app.ico               # Application icon / 应用程序图标
└─main.py               # Main entry point / 主程序入口
