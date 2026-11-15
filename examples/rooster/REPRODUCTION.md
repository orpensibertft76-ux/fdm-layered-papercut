# 鸡款复跑验收

用本目录的 reference.png、art.png 和 job.json 运行统一入口，包含 Blender 装盒预览。已在 Windows 实机验证。新生成工程的 8 份 G-code 与本目录 expected 内已验收工程逐字节一致。六张色片顶层路径各自连通，八盘预计 302.27 g、48988 秒。生成了逐片切片叠合、原设计对照和装盒斜视。未试印。

```powershell
python pipeline/run.py examples/rooster --out runs/rooster-001 --legacy-box --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe"
```

此验收针对仓库固定的生图输出。使用新图或不同的切片器版本时，以新的原生回读、实际路径和看图结果来验收。仅在相同输入和同版本环境下对照 G-code 字节。

默认六盘入口也已复跑，见 [公开版六盘验收](core-verified)。
