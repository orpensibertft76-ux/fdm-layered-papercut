# 盒体和试配件

019 盒体的画口 180 mm，盒外宽 199.4 mm、合盖厚 11.8 mm，画芯片腔 187.2 mm。上、下各三个燕尾，局部名义总间隙 0.02 mm。整盒验收范围为名义几何与实际切片，六键同时入槽及整盒止退手感待实测。底托和盖框各一盘，保持原盒体及支架接口。

017 试件由松到紧一至九道刻痕，对应 0.18 至 0.02 mm，总隙每档减 0.02 mm。两半都有同档刻痕。用户试打反馈为 0.02 mm 最合适，0.04 mm 仍松，0.03 mm 可作为下一轮候选。见 [九档试片及刻痕路径](fit/expected)。

## 从源参数复跑

在仓库根目录运行（以盒体为例，试片用 `hardware/fit` 同样处理）。每次用新编号生成目录，保持清单与相对路径一致。示例由本目录的实际参数和 P1S 参考配置生成。

```powershell
python hardware/box/建模.py
python Bambu_Toolchain/plate_project.py --manifest hardware/box/plates.json --work runs/box-native --checks runs/box-check --out runs/box.3mf
```

将已摆盘的工程在 Bambu Studio 切片，或复制到本机 ASCII 路径，用 `--arrange 0 --slice 0 --outputdir <目录> --export-3mf box-sliced.3mf <输入工程>`。回读每盘实际 G-code、网格和耗材，对照 [019 的成品和切片核验](box/expected)。各档试件在非功能面带实体标识，交付时核对刻痕是否进入顶层路径。
