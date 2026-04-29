# GameAgent: Voyager Minecraft Fork

这是一个基于 [MineDojo/Voyager](https://github.com/MineDojo/Voyager) 的工程化分支，用于在真实 Minecraft 1.19 LAN 世界中持续运行 Voyager，并通过 OpenAI-compatible 接口接入 `opencode.ai/zen/go/v1`。

这个仓库的重点不是复现论文页面，而是保留当前可运行代码、关键修复、以及本次真实运行得到的结果。

`report.pdf` 是对应的 LaTeX 实验报告，源码在 `report.tex`。

## 项目目标

- 在真实 Minecraft LAN 世界中持续运行 Voyager，而不是只做离线分析。
- 使用 `.env.local` 提供 `OPENAI_API_KEY`、`OPENAI_API_BASE`、`VOYAGER_MODEL_NAME`。
- 使用 `run_voyager.py` 从 `ckpt_voyager` 断点续跑。
- 对自定义 OpenAI-compatible API 做稳定性增强。
- 记录当前代码修改和实际任务结果。

## 当前入口

- 主运行脚本：`run_voyager.py`
- 快速测试脚本：`run.py`
- Minecraft 启动辅助：`launch_mc.py`

推荐运行方式：

```bash
./venv/bin/python run_voyager.py <LAN_PORT> 160 resume
```

环境变量放在 `.env.local`，该文件被 git 忽略，不会被提交。

## 关键代码改动

- `run_voyager.py`
  加载 `.env.local`，清理代理环境变量，统一使用 OpenAI-compatible 接口，并把环境步进超时提升到 `300s`。

- `voyager/utils/llm_utils.py`
  增加 LLM 重试和外层硬超时，避免模型请求无异常但无限卡住。

- `voyager/utils/fake_embeddings.py`
  对自定义 OpenAI-compatible endpoint 使用 `FakeEmbeddings`，规避部分 embedding 兼容性问题。

- `voyager/agents/action.py`
  `voyager/agents/curriculum.py`
  `voyager/agents/critic.py`
  `voyager/agents/skill.py`
  统一走应用层重试逻辑，并关闭底层 `ChatOpenAI` 自带重试以避免双重重试混乱。

- `voyager/env/bridge.py`
  强化 `/step` 和 `/start` 的恢复逻辑，mineflayer 重启后会重试连接，不再因为短暂启动竞态直接把整个学习流程打崩。

- `voyager/env/mineflayer/index.js`
  修复多处 mineflayer 生命周期问题：
  - `/step` 中使用 `activeBot` 捕获，避免全局 `bot` 被置空后再访问。
  - `/start` 生命周期改为对局部 bot 做空值安全处理。
  - stuck recovery 的 `teleportBot()` 避免在空 block 列表上取 `block.x`。

- `voyager/control_primitives/mineBlock.js`
  增加掉落等待与附近掉落物二次收集，减轻“挖到了但物品还没入包”的问题。

## 本次真实运行结果

截至当前 checkpoint：

- 完成任务数：`27`
- 失败任务数：`3`
- 学到的技能数：`28`

### 已完成任务

1. `Mine 1 wood log`
2. `Mine 3 spruce_log`
3. `Craft 4 spruce_planks`
4. `Craft 1 crafting_table`
5. `Craft 8 spruce_planks`
6. `Craft 1 wooden_pickaxe`
7. `Mine 3 cobblestone`
8. `Mine 1 coal_ore`
9. `Craft 4 sticks`
10. `Craft 1 stone_pickaxe`
11. `Mine 1 copper_ore`
12. `Mine 8 cobblestone`
13. `Craft 1 furnace`
14. `Smelt 4 raw_copper`
15. `Mine 1 lapis_ore`
16. `Mine 4 coal_ore`
17. `Mine 1 iron_ore`
18. `Craft 1 stone_sword`
19. `Equip stone_sword`
20. `Mine 2 iron_ore`
21. `Smelt 3 raw_iron`
22. `Craft 1 iron pickaxe`
23. `Mine 3 iron_ore`
24. `Mine 4 iron_ore`
25. `Smelt 4 raw_iron`
26. `Craft 1 iron_boots`
27. `Equip iron_boots`

### 已失败任务

- `Craft 12 spruce_planks`
- `Mine 1 spruce_leaves`
- `Kill 1 skeleton`

### 当前技能库

已生成的技能包括：

- `craftCraftingTable`
- `craftEightSprucePlanks`
- `craftFourSticks`
- `craftFurnace`
- `craftIronBoots`
- `craftIronPickaxe`
- `craftSprucePlanks`
- `craftStonePickaxe`
- `craftStoneSword`
- `craftWoodenPickaxe`
- `equipIronBoots`
- `equipStoneSword`
- `mineCoalOre`
- `mineCopperOre`
- `mineEightCobblestone`
- `mineFourCoalOre`
- `mineFourIronOre`
- `mineIronOre`
- `mineLapisOre`
- `mineOneCoalOre`
- `mineThreeCobblestone`
- `mineThreeIronOre`
- `mineThreeSpruceLogs`
- `mineTwoIronOre`
- `mineWoodLog`
- `smeltFourRawCopper`
- `smeltFourRawIron`
- `smeltThreeRawIron`

### 最新可见状态快照

来自 `voyager_live.log` 末尾的快照：

- Biome: `taiga`
- Position: `x=672.5, y=69.0, z=-399.5`
- Equipment: `iron_boots` 已装备
- Inventory 中的关键资源：
  - `iron_pickaxe: 1`
  - `stone_sword: 1`
  - `iron_boots: equipped`
  - `lapis_lazuli: 6`
  - `raw_iron: 5`
  - `copper_ingot: 4`
  - `coal: 2`
  - `cobblestone: 66`

## 为什么终止

从当前日志能确认的最后一个明确内部失败点是：

- 在任务 `Kill 1 skeleton` 期间，`voyager/env/bridge.py` 对本地 mineflayer HTTP 服务 `http://127.0.0.1:3000/step` 的请求发生 `ReadTimeout`。
- 当时超时时间已经提高到 `300s`，但依然超时。
- 随后 Python 侧抛出：`RuntimeError: Failed to step Minecraft server`。
- Voyager 按现有逻辑将 `Kill 1 skeleton` 标记为失败，并继续进入下一轮 curriculum 问答。

日志尾部没有留下另一个明确的 Python 致命异常或标准的“正常退出”记录，因此“最终为什么整个进程停了”无法从现有日志 100% 还原。比较保守的结论是：

- 最后一个明确的内部故障是 `Kill 1 skeleton` 的 `/step` 超时。
- 在那之后，程序至少还继续输出了一段 curriculum 分析。
- 最终停止更像是外部中断、会话结束、或日志之外的进程终止，而不是一个已经被完整记录的新代码异常。

## 如何复现/继续跑

1. 在 `.env.local` 中配置：

```dotenv
OPENAI_API_KEY=...
OPENAI_API_BASE=https://opencode.ai/zen/go/v1
VOYAGER_MODEL_NAME=kimi-k2.6
```

2. 启动 Fabric 1.19 客户端并把世界打开到 LAN。

3. 使用 checkpoint 续跑：

```bash
./venv/bin/python run_voyager.py <LAN_PORT> 160 resume
```

## 报告生成

编译 LaTeX 报告：

```bash
latexmk -xelatex report.tex
```

生成的 PDF 为 `report.pdf`。

## 仓库说明

- 上游项目：`MineDojo/Voyager`
- 当前仓库保留了上游结构，但 README 已改写为当前分支的工程说明。
- 原始安装说明仍可参考 `installation/` 与上游仓库文档。

## 安全说明

- `.env.local` 被 git 忽略，不会提交。
- 仓库中不应保存明文 API key。
- `run.py` 已改为从环境变量读取配置，不再包含硬编码密钥。

## 许可证

本仓库沿用上游 Voyager 的 [MIT License](LICENSE)。
