# 视频资源导出

`video-extract` 从 `app-export` 结果中发现并复制视频容器，同时生成物理文件清单和逻辑
版本索引。

## 使用方式

```powershell
python -m android_tool video-extract com.yoozoo.jgame.global --overwrite
```

默认目录：

```text
输入：exports/com.yoozoo.jgame.global/
输出：video_exports/com.yoozoo.jgame.global/
```

可使用 `--source` 和 `--output` 修改父目录，使用 `--quiet` 关闭复制进度，或使用
`--json` 输出机器可读摘要。

## 输出结构

工具保留每个物理视频的原始相对路径，因此 APK、OBB 和 upgrade 中的同名版本不会互相
覆盖。输出根目录另外包含：

- `video-manifest.json`：全部物理视频、来源层、大小、容器、分辨率和文件名时长。
- `video-index.json`：按逻辑路径合并版本，并按 `apk < obb < upgradelang < upgrade`
  选择默认版本。

`com.yoozoo.jgame.global` 当前样本包含 820 个 `.usm` 物理文件，共约 2.21 GiB；合并 14
组重复逻辑路径后共有 806 个逻辑视频。

## CRI USM

样本 `.usm` 文件以 `43 52 49 44`，即 ASCII `CRID` 开头，属于 CRI Middleware USM
容器。部分文件包含复合 VP9/透明通道式视频流；FFmpeg 能识别容器和基础元数据，但直接
重封装会报告损坏帧或不支持的 superframe 结构。因此当前工具只做原始容器的无损导出，
不自动生成 MP4。
