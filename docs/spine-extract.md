# Spine Extract

`spine-extract` 从 `app-export` 已经落盘的包目录中筛选 Spine 动画资源，并复制到
独立输出目录，便于后续用 Spine Viewer、TexturePacker 或自定义分析脚本查看。

```powershell
android-tool spine-extract com.yoozoo.jgame.global
```

默认读取：

```text
exports/com.yoozoo.jgame.global/
```

默认输出：

```text
spine_exports/com.yoozoo.jgame.global/
```

可以指定源目录和输出父目录：

```powershell
android-tool spine-extract com.yoozoo.jgame.global `
  --source exports `
  --output D:\spine-assets
```

重复提取时需要显式覆盖：

```powershell
android-tool spine-extract com.yoozoo.jgame.global --overwrite
```

扫描大型导出目录时，命令会显示扫描文件数、发现的 bundle 数和复制进度。需要关闭进度时：

```powershell
android-tool spine-extract com.yoozoo.jgame.global --overwrite --quiet
```

## 识别规则

工具会递归扫描 `exports/<package>/`，把同一目录中满足以下条件的资源识别为
Spine bundle：

- 存在 `.atlas`
- 存在同名 `.skel`、`.json` 或 `.bytes`

扫描范围包含 `apk/assets/res`、OBB 和 upgrade 数据。APK 作为最低优先级基础资源层；同一
逻辑路径在 OBB 或 upgrade 中存在时，APK 版本仍会保留在导出目录中用于审计，但不会重复
加入播放器索引。

匹配到的 bundle 会按原始相对路径输出，但只复制 `.atlas`、匹配的骨骼文件，以及 atlas
实际引用的贴图页。输出根目录会写入 `spine-manifest.json`，记录源路径、目标路径、
bundle 数量、文件数量和每个 bundle 内的 atlas、骨骼文件、图片文件。

如果 `upgrade/res/...` 只有新版本骨骼文件，工具会自动复用同一逻辑路径下
`obb/res/...` 的 atlas 和贴图，生成可独立加载的完整资源组合。

反过来，如果 upgrade 只更新了 atlas 和贴图，工具也会复用同一逻辑路径下 OBB 或 APK
中的骨骼文件。旧版 `app-export` 可能把 Windows 不便保存的文件名编码为 `%XX`；提取器会
读取 `metadata/path-map.json` 恢复 bundle 目录、atlas 和骨骼文件名，并按 atlas 中的
原始页名查找编码贴图，用 atlas 实际引用的名称写入输出目录。

同时会写入轻量的 `spine-index.json`。每个 skeleton/atlas 组合仍保留独立 bundle 记录，
索引 v2 另外提供 `scenes`：同目录存在 `<name>` 和 `<name>_bg` 时会生成背景加主体场景；
同一资源父目录下存在明确的 `_bg`、`_boom`、`_fg` 等同前缀资源时，会按背景、效果、
前景顺序生成多层场景。播放器左侧只显示一个组合条目，底部动作列表以主体层为准。

战斗目录中的 `attack`、`skill`、`hit`、`bullet` 资源不会仅凭名称自动组合。这些效果还
需要游戏配置提供触发时间、目标位置和缩放信息，缺少这些信息时直接叠加容易产生错位。

atlas 引用的贴图如果以 `UF 00 02` 开头，会在复制时自动完成 UF 解封、CCZ 解压和
ETC2/PVR 到 PNG 的转换；`spine_exports` 中的 `.png` 因而可以直接查看和供播放器加载。

以当前 `com.yoozoo.jgame.global` 导出为例，数据中存在标准 Spine 组合：

```text
data/credential-protected/files/obb/res/common/pet_spine/10700420/
├─ 10700420.atlas
├─ 10700420.png
└─ 10700420.skel
```

还可以看到 `knight_spine`、`effect_spine` 等成批资源目录，因此可以直接提取。

## 浏览器验证

仓库内的 `spine-player/` 使用与当前二进制骨骼匹配的 Spine 3.8 TypeScript 运行时，
会读取提取目录中的 `spine-index.json` 并加载对应 `.atlas`、`.skel` 和贴图：

```powershell
cd spine-player
npm install --ignore-scripts
npm run dev
```

该 3.8 兼容包声明了仅用于 Node 环境的可选 Canvas 依赖；播放器本身使用浏览器
WebGL，因此安装时加 `--ignore-scripts` 可避免在 Windows 上编译无关的原生模块。

游戏的 PVR v3 贴图头使用 `flags=0x2`，表示颜色已经预乘 Alpha。播放器因此使用
WebGL 预乘 Alpha 画布和 `ONE, ONE_MINUS_SRC_ALPHA` 混合，避免半透明贴图被再次乘
Alpha 后整体偏暗。

切换动作时，播放器会抽样整段动画及全部组合图层并锁定显示范围。播放过程中不会按
每一帧的附件包围盒重新居中，因此角色跳跃和特效显隐不会带动整个画面上下抖动。

当前 `com.yoozoo.jgame.global` 样本索引识别出 460 个组合场景：459 个角色主体加背景的
双层场景，以及 `eff_ui_birthdaycard_bg/boom/fg` 构成的一个三层场景。

## 当前样本验证结果

`pet_spine/10700420` 的 `.skel` 已成功解析，包含 `idle` 和 `skill` 两个动画。配套
`10700420.png` 的原始文件头是 `55 46 00 02`（ASCII 为 `UF`），不是 PNG 签名；
`spine-extract` 会在复制时自动完成解封，播放器可以直接加载贴图并渲染动画。完整的 UF
分析和转换说明见
[`docs/uf-extract.md`](uf-extract.md)。

当前样本重新导出得到 6,274 个资源任务、21,087 个清单文件和 6,753 组 atlas/骨骼
组合。逐个解析 atlas 后，贴图引用缺失、无效 PNG、清单缺失和播放器索引缺失均为 0。
源数据中的 6,050 个 `.skel` 只有 `knight_spine/300001` 的 OBB 与 upgrade 两份在所有
资源层都找不到 atlas，因此无法组成可播放动画。
