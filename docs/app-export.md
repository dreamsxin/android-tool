# App Export

`app-export` 根据包名导出可归属于应用的标准 Android 文件，包括：

- base APK 和 split APK
- `/data/user/0/<package>` 凭据加密私有数据
- `/data/user_de/0/<package>` 设备加密私有数据
- `/sdcard/Android/data/<package>`
- `/sdcard/Android/media/<package>`
- `/sdcard/Android/obb/<package>`
- `/sdcard/<package>`

私有数据优先使用 `su`，无 root 时尝试 `run-as`。非 root 且应用不可调试时，
Android 权限模型不允许读取私有数据，工具仍会导出 APK 和可访问的外部数据。

```powershell
python -m android_tool app-export com.example.demo
```

默认输出为 `exports/com.example.demo/`。

指定设备和输出父目录：

```powershell
python -m android_tool app-export com.example.demo `
  --serial emulator-5554 `
  --output D:\android-exports
```

最终目录始终使用包名。`export-manifest.json` 记录设备、root 状态、来源路径、
目标路径、估算大小、实际传输量及每项状态。重复导出需要显式添加 `--overwrite`。

Android 允许但 Windows 禁止的文件名字符会进行可逆百分号编码。例如 `:` 会写成
`%3A`；完整对应关系保存在 `metadata/path-map.json`。

应用也可能把文件写入无法从路径可靠归属的公共目录，工具不会把这些共享文件
自动计入，以免混入其他应用或用户数据。
