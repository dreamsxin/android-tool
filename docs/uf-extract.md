# UF Resource Extraction

`uf-extract` 用于处理该游戏资源文件中的 `UF 00 02` 封装。它读取已有的
`app-export` 目录，只输出能被原生 `cocos2d::FileUtils::decryptUF` 识别的 UF 2.0
资源。

```powershell
android-tool uf-extract com.yoozoo.jgame.global --png --overwrite
```

## 已确认的原生逻辑

`base.apk/lib/arm64-v8a/libcocos2dlua.so` 导出以下入口：

```text
cocos2d::FileUtils::decryptUF(unsigned char *, int, int *, int *, int *)
lua_cocos2dx_FileUtils_decryptUF(lua_State *)
```

对 `UF 00 02`，函数执行以下步骤：

1. 校验前两个字节为 `UF`，第三字节为 `0`，第四字节为版本 `2`。
2. 取第五字节作为 seed。
3. 使用 native `.rodata` 中的 33 字节表循环 XOR：
   `13 5B 0C 0D 66 16 22 2B 11 19 58 40 24 10 0E 42 31 57 38 2C 35 1C 0B 05 74 25 3A 69 14 0F 4D 07 1D`。
4. 文件尾部保存的 5 个字节经过 XOR 后成为解封 payload 的前 5 个字节。
5. payload 的第 6 至第 100 个字节继续 XOR；更后面的数据原样保留。

这不是 XXTEA。库中的 `xxtea_encrypt`、`xxtea_decrypt` 和
`LuaStack::setXXTEAKeyAndSign` 属于 Lua 脚本链路，`decryptUF` 自身没有调用它们。

## 贴图链路

当前样本的解封结果如下：

```text
UF 00 02
  -> CCZ!                 Cocos2d-x zlib wrapper
  -> PVR 3                ETC2 RGBA, pixel format 23
  -> PNG                 optional texture2ddecoder conversion
```

`--png` 需要安装 `texture2ddecoder` 和 `Pillow`。不加 `--png` 时，工具会保留解压后
的 PVR 数据，并在输出文件名后追加 `.decoded`。

默认输出到 `uf_exports/<package>/`，与 Spine 提取结果保持独立。工具会写入
`uf-manifest.json`，记录原始相对路径、seed、UF 版本、解封大小和内部格式。

导出目录通常较大，命令默认会显示：

```text
Scanning exports/com.yoozoo.jgame.global ...
Scanned 10,000 files; decoded 6,200 UF resources; current=...
```

进度写到 stderr，不影响 `--json` 的机器可读输出。需要关闭进度时添加 `--quiet`。
