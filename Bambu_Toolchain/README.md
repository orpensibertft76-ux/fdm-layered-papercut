# 拓竹切片工具链

与 Blender_Toolchain 分开：Blender 负责模型几何，这里负责打印配置、区域支撑、调用 Bambu Studio 切片和回读校验。

已在本机 Bambu Studio 02.08.02.61、P1S / 0.4 mm / PLA 上验证。AI 可以直接调用本目录的脚本，不依赖 GUI 点击或新增 MCP 服务。本工具不连接打印机，也不发送打印任务。

## 直接对 AI 说

“用拓竹工具链读取这个 3MF 的参数。”

“保留模型尺寸，把支撑速度改成 80、树支撑改成双壁，重新切片保存到新目录。”

“给模型指定区域的朝下面添加强制支撑，脸部指定区域禁止支撑，比较两版耗材和时间。”

AI 需要先检查模型，确定区域坐标；当前没有自动理解‘脸’‘手指’的分割模型。区域由模型原始毫米坐标的包围盒和可选法线条件定义。标记写入 3MF，支撑实体由拓竹切片引擎生成。

## 整理成一个拓竹多盘项目

用户要求“摆盘、整理成3MF、打开看看”时，先按[3MF项目整理流程](3MF项目整理流程.md)筛选生产零件并核对数量。默认仅交付一个可编辑3MF，不混入试片、旧版、日志或其它资料；不默认操作桌面。

已确定打印朝向的单色STL可使用共用打包器：

```powershell
python Bambu_Toolchain/plate_project.py --manifest 'Projects/项目名/工作文件/编号任务/plates.json' --work 'Projects/项目名/工作文件/编号任务/打包过程' --checks 'Projects/项目名/检查记录/编号任务' --out 'Projects/项目名/导出成品/编号任务/已摆盘_001.3mf'
```

清单模板：[examples/plate_project_manifest.json](examples/plate_project_manifest.json)，先复制到项目的工作文件/编号任务，再填写相对路径、实际机型与数量。可选依赖见 `requirements-plate-project.txt`。

打包器检查数量、板面和间距，用拓竹原生后台重新导出，再回读每件真实几何、盘内成员及配置；通过后才发布最终文件。所有子网格使用全局唯一ID，避免多个名称错误引用同一模型。它不执行切片，不改变模型朝向或比例，也不支持把彩色装配工程扁平化为STL。

## 可用操作

```powershell
.\Bambu_Toolchain\run-bambu.ps1 doctor
.\Bambu_Toolchain\run-bambu.ps1 inspect 'C:\完整路径\模型.gcode.3mf'
.\Bambu_Toolchain\run-bambu.ps1 prepare --model 'C:\完整路径\模型.stl' --settings-from 'C:\完整路径\原切片.gcode.3mf' --overrides 'C:\完整路径\参数.json' --regions 'C:\完整路径\支撑区域.json' --out 'C:\完整路径\新任务目录'
.\Bambu_Toolchain\run-bambu.ps1 slice --job 'C:\完整路径\新任务目录' --out 'C:\完整路径\新结果目录'
.\Bambu_Toolchain\run-bambu.ps1 slice --job 'C:\完整路径\新任务目录' --out 'C:\完整路径\直接打印结果目录' --print-file
.\Bambu_Toolchain\run-bambu.ps1 compare 'C:\完整路径\原切片.gcode.3mf' 'C:\完整路径\新结果目录\result.3mf' --out 'C:\完整路径\对比.json'
```

`--regions` 和 `--settings-from` 均可省略。默认配置是本机的 P1S 0.4、0.20mm Standard、Bambu PLA Basic；其他打印机使用 `--machine`、`--process`、`--filament` 指定已安装的完整配置名称。默认打印板为纹理 PEI，有参考工程时使用其中的打印板类型。只接受工艺配置字段作为 overrides，不接受打印机脚本或硬件参数混入工艺覆盖。

直接打印必须使用 `slice --print-file`。它调用拓竹原生 `--min-save`，输出 `result.gcode.3mf`，验证不含可编辑模型网格且包含 G-code。普通 `slice` 输出的是含模型的工程，不能仅改扩展名冒充纯切片文件。纯切片文件有意不保存三角面的绘制标记；区域标记在输入工程中保留，实际支撑应在输出 G-code 中检查。

Python 依赖：本机 Python 3.14，numpy 2.5.3。入口 `bambu.py`。`requirements.txt` 用于另建环境，不需要重复安装现有依赖。

### 参数示例

见 `examples/ngmm_support.json`。数值按拓竹配置格式保存为字符串；有些字段（如该版本的支撑速度）为数组，必须保留字段类型。切片后逐项检查 overrides 是否出现在导出配置中。打印首层速度等规则仍可覆盖实际局部速度，因此另读取 G-code 的指令速度。

### 区域支撑示例

```json
[
  {"name":"下表面", "mode":"enforce", "min":[10,0,19.99], "max":[30,10,20.01], "normal_z_max":-0.9}
]
```

`mode` 为 `enforce`（强制）或 `block`（禁止）；按三角面中心是否位于包围盒内选择，可加 `normal_z_max` 筛选朝下面。重叠区域按后写覆盖前写。未选到任何面即报错。STL 导入焊接完全相同的顶点，不缩放、不修形。区域涂色目前只支持二进制 STL；已带网格的 3MF 可读取、改全局工艺并重新切片，但不提供其多零件/变换下的区域绘制。ASCII STL 需先转换。

当前写入的是完整三角面的标记，不是拓竹画笔的子三角细分；细网格适合局部选择，粗网格需要先细分或更换选择方式。

## 已完成的验证

- 悬臂测试：手动支撑、未绘制时无支撑；底面标记 2 个面后出现 995 段支撑和 114 段界面挤出路径。涂色随输出工程保留。
- 禁止支撑测试：自动支撑模式下底面标记为禁止，切片无支撑，2 个禁止标记保留。
- 完整 ngmm：150 万面，保持约 105.66 mm 模型高度；生成 528 层，输出高度 105.60 mm，所有 11 个工艺覆盖回读匹配。
- ngmm 新版预计 4h34m47s、102.11 g；原切片为 3h31m59s、82.63 g。实际新支撑主体指令速度最高 80 mm/s。此版使用自动支撑，没有额外手工区域标记，尚未实物试印。
- STL 原始文件未覆盖；任务目录和输出目录若存在则拒绝写入。

完整模型验证成果：`output/ngmm_003/result.3mf`；校验：同目录 `verification.json`；配置来源和改动：`jobs/ngmm_002/manifest.json`。

## Windows 兼容处理

本机 CLI 对非 ASCII 路径处理存在问题。工具将输入与配置复制到 `%LOCALAPPDATA%\BambuAIToolchain\slice_*` 的独立任务目录，运行后台切片，再复制输出回用户指定目录。缓存保留用于排查，尚未自动清理。程序不改用户当前 GUI 工程、全局预设或默认配置。

导入用标准 3MF 和拓竹支持的 `paint_supports` 属性。不能给缺少拓竹项目元数据的普通 3MF 冒充完整 Bambu 项目标识；本机测试中这会导致切片器崩溃，已避开该输入方式。

## 目前的检查边界

已检查输出有 G-code、参数实际生效、支撑标记数量及状态回读一致、支撑路径和速度。未完成逐层支撑覆盖、尖端承托比例、支撑受力、热变形或碰撞仿真。`Floating vertical shell` 是路径类型，不等同于已证明不可打印。指令速度不是打印机实际加减速后的测量速度。不得把“切片成功”解释为“实物一定成功”。

## 依据

- [拓竹官方命令行接口](https://github.com/bambulab/BambuStudio/wiki/Command-Line-Usage)
- [官方 3MF 读写源码](https://github.com/bambulab/BambuStudio/blob/master/src/libslic3r/Format/bbs_3mf.cpp)
- [官方支撑标记序列化](https://github.com/bambulab/BambuStudio/blob/master/src/libslic3r/TriangleSelector.cpp)

reference 目录保留了实现时查阅的上游源码，非运行依赖。未分割整三角面时 enforce 状态 1 编码为十六进制 4，block 状态 2 编码为 8，并已用本机实际切片确认。
