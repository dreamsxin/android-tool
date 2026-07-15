# Android Dev Tools

面向 Android 开发、调试与问题定位的本地命令行工具箱。它把设备发现、应用查询、
数据导出等常见操作收敛到一个 CLI 中，并提供稳定的文本和 JSON 输出，便于人工使用、
脚本调用以及后续工具组合。

## 产品特点

- **快速**：优先直接访问本机 ADB Server，避免反复启动外部进程。
- **统一**：所有能力通过 `android-tool <command>` 调用，设备选择规则保持一致。
- **可组合**：命令支持 JSON 输出，可作为自动化脚本和诊断流水线的数据源。
- **可审计**：数据导出包含来源、大小、状态和文件名映射清单。
- **本地优先**：不上传设备信息、APK 或应用数据。

## 已实现工具

| 命令 | 用途 | 状态 |
| --- | --- | --- |
| `emulator-probe` | 查询 ADB 设备，或并发扫描本地模拟器端口 | 可用 |
| `app-list` | 列出已安装应用、包名和 APK 路径 | 可用 |
| `app-export` | 按包名导出 APK、私有数据和标准外部数据 | 可用 |
| `spine-extract` | 从导出结果中提取 Spine 动画资源 | 可用 |
| `uf-extract` | 解封 UF 00 02 资源，并将 ETC2 贴图转为 PNG | 可用 |
| `spine-player` | 在浏览器中验证 Spine 3.8 资源和动画 | 可用 |
| `adb-connect` | 连接、断开或检查 ADB 目标 | 可用 |
| `app-inspect` | 查询版本、UID、权限、组件和安装信息 | 可用 |
| `app-log` | 按包名或 PID 收集 logcat | 可用 |
| `app-control` | 启动、停止、重启、清缓存或清数据 | 可用 |
| `apk-install` | 安装、覆盖、降级或卸载 APK | 可用 |

## 快速开始

环境要求：Python 3.10 或更高版本，以及可用的 ADB Server。首次开发安装：

```powershell
python -m pip install -e .
android-tool --help
```

不安装命令入口时，可以在当前 PowerShell 会话中临时指定源码目录：

```powershell
$env:PYTHONPATH = "src"
python -m android_tool --help
```

### 1. 发现设备

默认直接查询 ADB Server，效果等同于 `adb devices -l`：

```powershell
android-tool emulator-probe
android-tool emulator-probe --json
```

需要发现尚未注册到 ADB 的本地模拟器服务时，显式启用端口扫描：

```powershell
android-tool emulator-probe --scan --start 5554 --end 5682 --timeout 0.2
```

### 2. 查询应用

```powershell
android-tool app-list
android-tool app-list --third-party
android-tool app-list --system --include-path
android-tool app-list --serial emulator-5554 --json
```

只有一个在线设备时会自动选择；存在多个在线设备时必须使用 `--serial`，避免操作
错误的目标。

### 3. 导出应用数据

使用中性示例包名导出 APK 和可访问的应用数据：

```powershell
android-tool app-export com.example.demo
```

指定设备、输出目录或覆盖已有结果：

```powershell
android-tool app-export com.example.demo --serial emulator-5554
android-tool app-export com.example.demo --output D:\android-exports
android-tool app-export com.example.demo --overwrite
```

默认输出目录为：

```text
exports/com.example.demo/
├─ apk/                          # base APK 和 split APK
├─ data/                         # 凭据加密和设备加密私有数据
├─ external/                     # Android/data、media、obb 等外部数据
├─ metadata/                     # package 信息和路径映射
└─ export-manifest.json          # 来源、大小和导出状态
```

私有目录需要设备 root 权限，或应用允许 `run-as`。Android 允许但 Windows 不支持的
文件名会进行可逆编码，映射记录在 `metadata/path-map.json`。

### 4. 提取 Spine 动画资源

从已有 `app-export` 结果中抽取 `.atlas`、`.skel` 和配套贴图：

```powershell
android-tool spine-extract com.yoozoo.jgame.global
```

默认读取 `exports/com.yoozoo.jgame.global/`，输出到
`spine_exports/com.yoozoo.jgame.global/`。重复提取时添加 `--overwrite`。输出目录会保留
原始相对路径，将 atlas 引用的 `UF 00 02` 贴图直接转换为标准 PNG，并写入
`spine-manifest.json` 方便审计，同时生成 `spine-index.json` 供播放器快速列出动画目录。
同目录存在多套 skeleton 时，索引会分别列出每套动画；`upgrade` 只有新骨骼文件时，会
自动复用同逻辑路径下的 `obb` atlas 和贴图。
`apk/assets/res` 中的基础 Spine 资源也会提取；播放器索引按 `apk < obb < upgrade` 处理
同路径资源，避免 APK 内旧版本覆盖更新数据。

扫描大型导出目录时会显示扫描文件数、发现的 Spine bundle 数和复制进度；使用
`--quiet` 可以关闭进度，只保留最终摘要。

提取完成后启动 Spine 3.8 播放器：

```powershell
cd spine-player
npm install --ignore-scripts
npm run dev
```

播放器读取上面的 `spine-index.json`，左侧直接列出所有动画目录；点击目录后加载其中的
skeleton、贴图和动作，可切换动作、循环状态、时间轴、速度和显示缩放。
`spine-extract` 会自动将 atlas 引用的 `UF 00 02` 贴图转换为标准 PNG，因此 Spine 播放器
不需要再执行 `uf-extract`。如果需要解封整个应用中的所有 UF 资源，再使用：

```powershell
android-tool uf-extract com.yoozoo.jgame.global --png --overwrite
```

`uf-extract` 默认输出到 `uf_exports/com.yoozoo.jgame.global/`。`--png` 会把 UF -> CCZ
-> PVR 链路中的 ETC2 RGBA 贴图转换为标准 PNG；需要安装可选依赖：

```powershell
python -m pip install texture2ddecoder Pillow
```

扫描大型导出目录时，命令默认会在 stderr 显示扫描文件数和已解封资源数；需要只保留最终
摘要时使用 `--quiet`。使用 `--json` 时进度仍写入 stderr，不会污染 JSON 输出。

## 后续规划

下一阶段继续补齐更完整的日常调试闭环。

| 优先级 | 计划命令 | 核心能力 |
| --- | --- | --- |
| P1 | `app-restore` | 将 `app-export` 结果恢复到兼容设备 |
| P1 | `screen` | 截图、录屏、坐标点击、滑动和文本输入 |
| P1 | `performance` | 汇总 CPU、内存、启动耗时、帧率和耗电信息 |
| P1 | `file-transfer` | 在设备与本地之间浏览、上传和下载文件 |
| P2 | `network-debug` | 管理代理、端口转发、反向代理和网络诊断 |
| P2 | `diagnostic-report` | 汇总设备信息、日志、进程和 bugreport，生成诊断包 |

推荐下一项实现 `adb-connect`。它可以直接消费 `emulator-probe` 的
`connect_target`，让设备发现结果立即进入可用连接状态。

## 项目结构

```text
android-tool/
├─ src/android_tool/
│  ├─ cli.py                     # 统一命令入口
│  ├─ core/                      # ADB、网络和通用能力
│  └─ tools/                     # 独立工具模块
├─ tests/                        # 单元测试
├─ docs/                         # 设计、使用说明和排障记录
├─ scripts/                      # 本地开发脚本
├─ exports/                      # 本地导出结果（Git 忽略）
└─ pyproject.toml                # Python 包和 CLI 配置
```

## 安全边界

- 仅对你拥有或获准调试的设备和应用执行操作。
- 导出结果可能包含账号、令牌、数据库等敏感信息，`exports/` 已默认加入 Git 忽略。
- `--overwrite`、清理数据和未来的恢复命令属于破坏性操作，应在执行前确认目标设备、
  包名和备份状态。

## 开发与验证

```powershell
python -m pip install -e .
python -m pytest
```

新增工具时应保持三个约定：复用统一设备选择、同时考虑文本和 JSON 输出、为命令解析
与核心行为添加测试。
