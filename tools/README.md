# 开发与运维工具

`scripts/` 保留原命令名，负责设置源码路径、传递参数和退出码；`tools/` 保存配置分发、项目检查、备份下载、静态归档和品牌素材处理。模型采集、训练、验证、交接及报告的业务代码位于 `ml/src/recognition/`。

| 实现 | 职责 | 命令入口 |
| --- | --- | --- |
| `config/distribution.py`、`config/cli.py` | 固定版本配置校验、原子分发与导出 | `scripts/sync-configs.py` |
| `checks.py` | 组织独立的 Python、Node 和浏览器检查进程 | `scripts/check-project.py` |
| `database_backup.py` | 固定主机指纹的 SSH 下载及备份完整性核对 | `scripts/download_database_backup.py` |
| `web_bundle.py` | 按可信运行清单检查依赖、生成可复现的完整 /ios 归档 | `scripts/package-web.py` |
| `brand_assets.py` | 从已有品牌原稿生成部署尺寸 | `scripts/generate-brand-assets.py` |

`scripts/config_distribution.py` 和 `tools/data/legacy.py` 仅是兼容导入，保留原模块身份。新代码直接导入 `tools.config.distribution` 或 `recognition.legacy_data`。

旧采集流程的字段校验、图片检查和按实物划分逻辑已移至 `recognition.legacy_data`。`scripts/check_manifest.py` 与 `scripts/split_dataset.py` 继续负责启动和参数传递，原命令可用。

底层 CSV/JSON 读写、SHA-256 和原子替换来自 `ml/src/recognition/manifest_io.py`；`recognition.common` 保留原函数名作为兼容导出。共享实现只依赖标准库，图片清晰度计算在实际调用时才导入 NumPy/Pillow。

| 流程 | 清单规则 | 划分及审核规则 | 入口 |
| --- | --- | --- | --- |
| 旧采集 | 严格 11 列，清理字段首尾空白，拒绝缺列/多列 | 类内按 object_id 分组，60/20/20；默认 approved，显式 `--include-pending` 可纳入 pending | `scripts/check_manifest.py`、`scripts/split_dataset.py` |
| 正式训练 | 默认输出 26 列，保留来源/许可/group_id 等；读取保留扩展列和值 | 按对象与审核组的连通关系隔离，仅 approved；训练/验证约 75/25；独立测试另行冻结 | `python -m recognition audit/split`、`recognition.data`、`recognition.evolution` |

两套规则共用文件操作，分别保留自己的业务约束。JSON 和 CSV 在同目录使用唯一临时文件，成功序列化后原子替换；失败清理临时文件并保留原文件。正式流程继续保留 Windows 文件占用重试。

训练的源码快照仍覆盖 `recognition/` 下所有 Python 文件，包括数据 I/O 和迁入的业务流程。新源码运行训练须使用新实验 ID，不修改已冻结的模型与数据；交付打包收录工具及它们的轻量依赖。业务模块导入不解析命令参数、不启动采集/训练/备份；可选训练和图片依赖在实际执行时加载。

回归检查入口见 [测试说明](../tests/README.md)。
