# 跨模块共享约定

`categories.json` 保留固定基准 `campus-gpu-v1` 使用的 `campus-10-v2` 原始字节，其键盘口径为独立外接键盘。2026年10月9日用户将新系列的键盘范围扩大为包含笔记本内置键盘，新口径冻结在 `category-versions/campus-10-v3.json`，供审核台和后续 `campus-evolve-*` 批次使用。键盘须是清楚可辨的主体，或能裁出完整主体；仅作背景、严重遮挡的照片仍拒绝。十类ID、标签及顺序不变；v1/v2历史数据与成绩不改写。
`categories.example.json` 保留为初始化时的草案示例。正式训练、labels和交接使用冻结文件。

开始数据标注和模型训练前，由组长、模型负责人、数据负责人共同确认类别，发布正式 `categories.json`，记录类别版本，并由该文件生成模型的 `labels.txt` 与数据库初始化数据。Android 和 Web 使用相同的 ID 与显示名称。

类别 ID 已固定为 0 至 9，与模型输出索引一一对应。冻结后不能因显示名称或数组排序的变化而悄悄改动 ID；需要变更时发布新映射版本，同时检查已有模型与数据库记录的兼容关系。

API 和模型契约分别保存在 `docs/api/README.md`、`docs/model-contract.md`，后续真实共享文件统一放到此目录。

`device-results/` 提供先导和expanded-cpu-v1试验包的参考张量/图片链路结果空表，不能把空表或参考答案当实际结果。
新模型应运行 `scripts/make-handover-report.py` 从对应发布包生成表格，详见 `docs/ml-handover.md`。
