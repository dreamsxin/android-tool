# App List

`app-list` 通过 ADB Server 在目标设备上执行 `pm list packages`，列出当前安装的应用包。

## 设备选择

- 只有一个 `device` 状态的设备时自动选择
- 多个在线设备时要求使用 `--serial`
- `offline` 和 `unauthorized` 设备不会被自动选择

## 过滤选项

- 默认：全部已安装包
- `--third-party`：仅第三方应用
- `--system`：仅系统应用
- `--include-path`：同时输出 APK 路径
- `--json`：输出设备、范围、数量和包列表的结构化数据

该工具直接使用 ADB Host Protocol，不依赖厂商 ADB 可执行文件的位置。
