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

## 识别规则

工具会递归扫描 `exports/<package>/`，把同一目录中满足以下条件的资源识别为
Spine bundle：

- 存在 `.atlas`
- 存在同名 `.skel`、`.json` 或 `.bytes`

匹配到的 bundle 目录会按原始相对路径整体复制，确保 `.atlas` 引用的贴图和额外变体
一起保留。输出根目录会写入 `spine-manifest.json`，记录源路径、目标路径、bundle
数量、文件数量和每个 bundle 内的 atlas、骨骼文件、图片文件。

以当前 `com.yoozoo.jgame.global` 导出为例，数据中存在标准 Spine 组合：

```text
data/credential-protected/files/obb/res/common/pet_spine/10700420/
├─ 10700420.atlas
├─ 10700420.png
└─ 10700420.skel
```

还可以看到 `knight_spine`、`effect_spine` 等成批资源目录，因此可以直接提取。
