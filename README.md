# FDM 分层剪纸

用于把插画、剪纸参考图或分色遮罩设计成多张可独立拿起的 FDM 单色镂空薄片，按顺序叠装入框。

## 安装到 Codex

将本仓库克隆或下载到个人技能目录，目录名使用 `fdm-layered-papercut`。可用位置为 `~/.agents/skills/`（Windows 上为 `%USERPROFILE%\.agents\skills\`）。也可放到项目根目录的 `.agents/skills/`，供该项目使用。参见 [Codex 安装说明](https://developers.openai.com/api/reference/cli)。

安装后，确保 `SKILL.md` 和 `references/` 位于同一个技能目录内。

## 使用示例

在 Codex 中输入：

> 用 $fdm-layered-papercut 把这张插画拆成可叠装的单色镂空薄片。先交每层遮罩和正视叠合图，检查每片是否连到定位边，并标出从正面和斜侧面能看见的连筋。

## 文件

- [SKILL.md](SKILL.md) 说明如何拆层、连接孤岛、检查遮挡和装配，以及验证最终网格和 3MF 摆盘。
- [祥羊案例](references/ram-case.md) 记录设计迭代、侧视遮挡检查和验证范围。

仓库包含流程和案例文档。建模、导出和回读需要项目所用的 CAD 或切片工具。案例记录涵盖几何和 3MF 回读检查，切片和实物试印尚未进行。

**贡献者**　小文不闻
