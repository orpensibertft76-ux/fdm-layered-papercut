# FDM 分层剪纸生产流程

输入「十二星座」「梅兰竹菊」这样的主题，生成原设计和可生产分色稿，再由程序转换成可装框的单色整片。AI 的执行顺序和验收条件见 [AGENTS.md](AGENTS.md)。

## 安装技能

复制整个 `skills/fdm-layered-papercut/` 到 Codex 的个人技能目录或项目技能目录。要运行下方切片流程，请克隆整个仓库。

## 先复跑已知样板

Windows 安装 Python、Bambu Studio（已验证 02.08.02.61）。装盒渲染使用 Blender 5.2。安装 Python 依赖后，从带齐两张图和任务配置的样板运行。支持 `--bambu <exe>` 和 `--blender <exe>`，每次使用新目录。

```powershell
python -m pip install -r requirements.txt
python pipeline/run.py examples/rooster --out runs/rooster-review --review-only
python pipeline/run.py examples/rooster --out runs/rooster-core
```

默认是一款六盘的独立画芯。要重新生成旧版八盘鸡款示例时加 `--legacy-box`。新款使用独立的 [019 盒体](hardware/box/expected)，可与画芯同时试制。六色各一张，外宽 186 mm、厚 1.2 mm，画口 180 mm。当前设备配置为 P1S／0.4 mm／PLA。019 盒体为六处燕尾两丝样件，短试件的配合已有实测，完整盒的配合待验证。

## 从新主题跑两轮生图

1. **主题 → 原设计**。先写主体数量、轮廓、部位配色、留白和装饰密度。用 [祥羊设计](examples/sheep/reference.png) 或已验收的同系列正视图作为风格参考，附给 AI 的生图工具。看过并确认主体和风格后，把选定图保存为 `reference.png`。这里有[真实十二生肖第一轮提示词和生图结果](examples/series)。
2. **原设计 → 生产分色图**。把选定的 `reference.png` 真实传给图像编辑模型，按[两轮生图规范](IMAGE_INPUT.md)和各部位配色约束做第二轮。保留姿态、构图和纹样，把生成结果保存为 `art.png`。鸡、龙附实际用过的第二轮提示词。图像生成由克隆者的工具完成，PNG 是和本地程序的交接文件。
3. **预审 → 分片 → 切片**。拷贝一个 `job.json`，填写两图画口坐标和背到前的色序。先用 `--review-only` 生成原设计、生图、固定六色、分片正视四图及斜视和颜色统计。面积小且散的色片优先靠后，面积大、连续且遮筋有效的色片靠前。金边留画芯，外框由盒体提供。默认整片开孔，充分留料。四图对照通过后用新目录正式运行。超过 3% 正视遮罩偏离会拦截，低于阈值仍要看图确认。
4. **装盒和交付**。每款给原图、生产稿、独立可编辑已切片 3MF、逐片挤出路径累加与原稿对照。传入 Blender 路径时，生成线下装配渲染；模型为本轮画芯与独立盒体的组合。标注剩余露筋、细孔与实物验证状态。试配件、外壳和画芯各自使用自己的项目。

## 可核对的成品

- [祥羊原设计、装盒渲染与历史工程](examples/sheep)
- [龙画芯](examples/dragon)、[蛇画芯](examples/snake)、[马画芯](examples/horse)
- [鸡款原图、提示词、任务输入、分片与已切片样板](examples/rooster)
- [九档带刻痕试件与 019 整盒](hardware/README.md)
- [拓竹命令行工具](Bambu_Toolchain/README.md)和[可安装技能](skills/fdm-layered-papercut/SKILL.md)

试打由使用者发起。公开案例使用设计图和数字渲染。本地日志、用户设置、凭据及缓存留在本机。

## 许可

本仓库的工作流代码与文档采用 MIT 许可。参考素材和装配渲染用于复跑与案例对照，权利归原作者。拓竹软件和生图模型按各自许可使用。
