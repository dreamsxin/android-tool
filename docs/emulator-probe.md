# Emulator Probe

`emulator-probe` 是工具箱的第一个工具，用于列出本机 ADB 已知设备，并识别本地模拟器连接目标。

## 探测策略

默认通过 ADB Host Protocol 直接查询本机 ADB Server（默认 `127.0.0.1:5037`），
不会扫描模拟器端口，也不需要先找到 `adb.exe`。如果服务尚未运行，工具再查找并执行
`adb devices -l`。工具依次从以下位置查找 ADB：

- `ADB` 环境变量指定的文件
- 当前 `PATH`
- `ANDROID_SDK_ROOT/platform-tools`
- `ANDROID_HOME/platform-tools`
- Windows 默认的 `%LOCALAPPDATA%/Android/Sdk/platform-tools`

只有指定 `--scan` 时，才并发扫描 `127.0.0.1:5554-5682`：

- 偶数端口按 emulator console 处理
- 相邻奇数端口按 adb 端口处理
- 只要 console 或 adb 任一端口可连接，就输出一条候选模拟器记录

## 输出字段

- `serial`: ADB 设备序列号
- `state`: `device`、`offline` 或 `unauthorized` 等 ADB 状态
- `connect_target`: 本地模拟器下一步可使用的连接目标
- `console_target`: 模拟器控制台目标，例如 `127.0.0.1:5554`
- `adb_connect_target`: 下一步 adb 连接目标，例如 `127.0.0.1:5555`
- `open_services`: 当前探测到的可连接服务

## 后续扩展

- 增加一键 `adb connect`
- 增加 mDNS 或第三方模拟器端口识别
