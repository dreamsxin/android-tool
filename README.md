# Android Dev Tools

一个用于沉淀 Android 开发、调试、诊断小工具的本地工具箱项目。

## 目录规划

```text
android-tool/
├─ src/android_tool/
│  ├─ cli.py                     # 统一命令入口
│  ├─ core/                      # 通用能力：端口、ADB 可执行文件和输出解析
│  └─ tools/                     # 独立工具模块
│     ├─ emulator_probe.py       # 本地模拟器服务探测
│     └─ app_list.py             # 已安装应用包列表
├─ tests/                        # 单元测试
├─ docs/                         # 工具设计、使用说明、排障记录
├─ scripts/                      # 本地开发脚本
└─ pyproject.toml                # Python 包和 CLI 配置
```

## 第一个工具：本地模拟器服务探测

默认直接查询本机 ADB Server，效果等同于 `adb devices -l`，通常可以立即得到
ADB 已知的模拟器和真机，并为本地模拟器生成下一步可用的 `connect_target`。
如果 ADB Server 尚未运行，工具会查找并执行 `adb devices -l` 来启动它。

运行：

```powershell
python -m android_tool emulator-probe
```

只输出 JSON，方便后续给 adb 连接工具复用：

```powershell
python -m android_tool emulator-probe --json
```

ADB 不可用或需要发现尚未注册到 ADB 的服务时，可显式启用并发端口扫描。
Android Emulator 常见端口规律：

- 偶数端口是 emulator console，例如 `5554`
- 后一个奇数端口是 adb 端口，例如 `5555`
- 一组本地模拟器通常表现为 `127.0.0.1:5554/5555`

指定范围：

```powershell
python -m android_tool emulator-probe --scan --start 5554 --end 5682 --timeout 0.2
```

ADB 列表输出中的 `connect_target`，或扫描输出中的 `adb_connect_target`，
可以作为下一步 `adb connect` 的目标，例如：

```powershell
adb connect 127.0.0.1:5555
```

## 第二个工具：已安装应用列表

自动选择唯一在线设备，列出已安装应用的包名：

```powershell
python -m android_tool app-list
```

常用筛选和结构化输出：

```powershell
python -m android_tool app-list --third-party
python -m android_tool app-list --system --include-path
python -m android_tool app-list --serial emulator-5554 --json
```

有多个在线设备时必须通过 `--serial` 指定目标，避免查询错误的设备。

## 开发

```powershell
python -m pip install -e .
python -m pytest
```
