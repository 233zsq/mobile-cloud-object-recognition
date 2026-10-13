# 跨模块共享约定

`categories.json` 保留固定基准 `campus-gpu-v1` 使用的 `campus-10-v2` 原始字节，其键盘口径为独立外接键盘。2026年10月9日确认新系列键盘包含笔记本内置键盘，记录为不可变的 `category-versions/campus-10-v3.json`；随后将“雨伞”扩大为“伞”，包含雨伞、手持遮阳伞及庭院或沙滩遮阳伞，冻结为 `category-versions/campus-10-v4.json`。审核台及后续 `campus-evolve-*` 新批次使用v4，排除帐篷、遮阳棚和降落伞。目标须清楚可辨且为主要主体，或能裁出完整主体；仅作背景、严重遮挡的照片仍拒绝。十类ID、标签键及顺序不变，伞仍为ID=1、`umbrella`；v1/v2/v3历史文件、数据与成绩不改写。
`categories.example.json` 保留为初始化时的草案示例。正式训练、labels和交接使用冻结文件。

开始数据标注和模型训练前，由组长、模型负责人、数据负责人共同确认类别，在 `category-versions/<版本>.json` 发布不可变的正式版本，由指定版本生成 `labels.txt` 和各端配置副本。`categories.json` 继续保留 v2 基准兼容字节。Android、Web、数据库可以采用不同历史类别版本，十类 ID 和标签顺序相同，具体口径和中文名称以各自版本为准。

类别 ID 已固定为 0 至 9，与模型输出索引一一对应。冻结后不能因显示名称或数组排序的变化而悄悄改动 ID；需要变更时发布新映射版本，同时检查已有模型与数据库记录的兼容关系。

API 和模型契约分别保存在 `docs/api/README.md`、`docs/model-contract.md`，后续真实共享文件统一放到此目录。

`device-results/` 提供先导和expanded-cpu-v1试验包的参考张量/图片链路结果空表，不能把空表或参考答案当实际结果。
新模型应运行 `scripts/make-handover-report.py` 从对应发布包生成表格，详见 `docs/ml-handover.md`。

## 版本分发与检查

`config-distribution.json` 固定类别源、模型发布元数据和标签文件的 SHA-256、策略源及各端的版本绑定。类别来源统一为 `category-versions/`；策略来源统一为 `policies/<策略版本>/`。v2 类别归档逐字节复制历史 `categories.json`，v3 的 `scope-knownness-v1` 逐字节归档自已发布模型包，模型发布包中的原文件继续保留。ML 显式指定类别版本时优先读取归档，旧工作区只有 v2 基准副本时仍可回退读取。

| 分发组 | 当前来源与用途 | 目标 |
| --- | --- | --- |
| `legacy` | `campus-10-v2`；历史基准只读兼容 | `shared/categories.json` |
| `database` | `campus-10-v2`；已存在的历史种子只读兼容 | `database/seeds/categories.campus-10-v2.json` |
| `android` | `campus-10-v4` 类别，v2 模型的 `scope-basic-v1` 回退策略 | assets 中的 `categories.json`、`scope/scope-policy.json` 和校验文件 |
| `backend` | v2 模型的 `scope-basic-v1` 回退策略 | `backend/policies/scope-basic-v1.json` |
| `web` | `campus-evolve-v2` 的模型契约、v4 类别与基础策略 | `web/ios/categories.json`、`web/ios/model-contract.json` |

从仓库根目录执行，只依赖 Python 标准库：

```bash
python scripts/sync-configs.py check
python scripts/sync-configs.py generate
python scripts/sync-configs.py check --target web
python scripts/sync-configs.py export --category-version campus-10-v4 --model-version campus-evolve-v3 --output tmp/config-v3
```

`check` 只读核对源哈希、类别 ID/顺序、模型标签与类别口径、模型/策略身份及副本字节，发现差异返回退出码 1。`generate` 先完整验证来源和绑定，仅修复选中的配置副本；已有历史基准或种子发生差异时停止，不覆盖历史文件。每文件原子替换，写入失败时回退已替换文件。可重复加 `--target` 选择分发组。

`export` 按指定类别版本生成类别、标签和 SHA-256 收据；指定模型时另外生成 Web 契约及该模型对应的策略与校验文件。输出目录必须不存在，拒绝类别、模型与策略混用。`--policy-version` 可显式指定匹配策略，默认使用模型绑定。它准备配置交付副本，不修改已发布模型包，也不切换各端正在使用的模型。模型权重和实际张量校验继续使用模型交接工具。

基础策略保持原 CRLF 字节，v3 策略保持原 LF 字节；Web 按契约中的换行声明恢复策略字节再校验哈希。更新配置须先新增版本及哈希，再审阅分发绑定变化，完成 `generate` 和 `check`。冻结源内容或哈希发生变化时应调查或恢复原件，不能通过重算哈希掩盖历史改写。

回归：`python -m pytest tests/test_config_distribution.py` 和 `node --test web/ios/tests/core.test.cjs`。源归档及模型身份是不可变输入，生成动作不会写入模型发布目录、冻结数据或验收状态文件。
