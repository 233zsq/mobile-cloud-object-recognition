# 系统验收与联调

## 自动检查入口

从仓库根目录执行 `python scripts/check-project.py`，默认运行 `core`。重复 `--group` 可组合检查，每个组件使用独立 pytest 进程，避免同名测试文件相互覆盖。任一检查失败时总退出码为 1；检查产生的临时文件位于忽略的 `tmp/check-project-<唯一ID>/`。

| 分组 | 内容 | 环境要求 |
| --- | --- | --- |
| `core` | 配置分发核对、报告/数据基准、工具导入与命令边界、静态依赖/归档、Web 核心及服务逻辑 | Python 3.12+、pytest、Node；无需 NumPy、Flask 或 TensorFlow |
| `backend` | Flask 接口、入库去重、纠错、统计、推理边界 | 独立环境安装 `backend/requirements-dev.txt` |
| `review` | 审核站 HTTP/SQLite、租约与 AI 边界，以及路由/CLI/数据库兼容、多应用隔离和服务回滚 | 独立环境安装 `review/requirements-dev.txt` |
| `ml-data` | 正式清单、分组隔离、版本迁移、评估及恢复约束；排除训练集成用例 | 独立环境安装 `-e 'ml[test,analysis]'`，无需 TensorFlow/LiteRT；运行时用例使用隔离 fake |
| `ml-integration` | 梯度更新、模型保存恢复与实际 TensorFlow/Keras 调用 | 安装项目训练锁及 recognition；已有 GPU 环境按 `ml/README.md` 激活 |
| `web-browser` | 实际页面下的识别确认、纠错、导航、备份、统计筛选和并发响应 | Node 20+、`npm ci --prefix web`，以及 Playwright Chromium 或本机 Edge；全部 API 模拟 |
| `deploy` | 源码归档、发布包校验和静态部署边界 | Linux、`backend/requirements-dev.txt`（包含 pytest 与 SQLAlchemy）；不连接服务器、不执行真实部署 |

示例：

```bash
python -m pip install pytest==9.1.1
python scripts/check-project.py --group core
python scripts/check-project.py --group backend --python backend/.venv/bin/python
python scripts/check-project.py --group review --python review/.venv/bin/python
python -m pip install -e 'ml[test,analysis]'
python scripts/check-project.py --group ml-data
python scripts/check-project.py --group ml-integration --python .venv/bin/python
python scripts/check-project.py --group web-browser
python scripts/check-project.py --group deploy
python scripts/check-project.py --group core --group backend --list
```

Windows 的 `--python` 使用对应环境下的 `Scripts/python.exe`。后端与审核站的 pytest 锁版本不同，分别建立环境，避免把两个 requirements 文件装入同一环境。MySQL 用例未设置 `TEST_MYSQL_ADMIN_URL` 时明确跳过；需要验证时按后端说明提供本机 `127.0.0.1` 的测试管理员连接，自动创建和删除 `test_recognition_` 临时库，不使用生产库。

`.github/workflows/checks.yml` 在 PR、main/opti/codex 分支推送和手动触发时使用相同入口；core 在 Windows/Linux 运行，后端、审核、ML 非训练用例、部署边界与 Chromium 浏览器测试在 Linux 分别运行。浏览器依赖由 `web/package-lock.json` 固定。CI 不包含真实 MySQL、GPU、Android 构建或服务器验收；这些检查按各模块环境另行执行。

浏览器安装和已有 Edge 的运行方式见 [Web 说明](../web/README.md#回归检查)。`core` 保持轻量，不要求安装 Playwright。

## 测试公共代码

- `backend/tests/conftest.py`：应用、客户端、隔离数据库和记录上传 fixture；`backend_support.py`：推理 fake。
- `review/tests/conftest.py`：应用 fixture；`review_support.py`：HTTP、SQLite 与 AI 辅助函数。单独运行任何测试文件都不依赖先收集其他测试模块。
- `review/tests/fixtures/review-contract.json`：审核站拆分前的 24 个路由、8 个 CLI 命令参数及数据库表/索引结构；`test_refactor_contract.py` 同时验证多应用隔离、服务事务回滚和导入时不启动任务。
- `ml/tests/conftest.py`：`data_workspace` 与 `evolution_workspace`，按需加载图片依赖，分别保持正式划分和批次迁移场景。实际训练用例标记为 `integration`。
- `tests/fixtures/data-tools/` 与 `ml/tests/fixtures/reports/`：重构前输出基准；前者校验 CSV 原始字节和冻结元数据，后者校验报告正文。

新增辅助函数放入支持模块或 fixture，测试文件不互相导入。模块测试继续留在所属模块，根目录 `tests/` 管理跨模块契约、工具和系统验收。

## 系统验收

负责人：组长兼测试负责人，各模块负责人协助。

- `acceptance-cases.csv`：按实际证据记录验收结果；已执行的条目包含 `passed`，真机联调、性能及独立评估缺口继续保留 `pending`。
- `integration/`：后续端云接口与系统联调测试。
- `fixtures/`：经过审核的小型测试输入；不要混入冻结测试集或未审核照片。
- `evidence/`：截图、测试日志与结果摘要；大体积录屏另行保存并记录位置。

每次执行保存代码、数据、模型、APK 版本、设备、执行人、时间、预期与实际结果和证据路径。失败如实记录，尚未执行不标为通过。

独立模型评估和真机性能结果整理到 `experiments/reports/`。按计划书，性能测试先预热 20 次，再测至少 100 次，记录预处理与推理的 P50/P95、设备条件与模型大小。验收目标属于计划，实际结果执行后填写。

新增云端模型加载、单图片推理、异常图片与端云对比验收。使用相同FP32模型、标签和图片，两端分别预热后计时，区分纯推理、预处理加推理和手机请求至返回的总等待时间，登记网络、CPU、内存和失败率。同图对比与`/api/infer`请求不自动入库，日常采集只计一次；云端异常时手机离线流程仍须可用。
