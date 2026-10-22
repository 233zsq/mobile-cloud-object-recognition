<img src="web/assets/images/brand-mark.png" width="104" height="104" alt="校园物品识别：扫描标签图标">

# 移动端物品图像采集与识别系统

计算机系统项目综合实践：手机拍照，在 Android 端离线识别物品，再把识别记录同步到云端，由 Web 页面展示统计结果。

后端采用 **Python Flask**，云端部署与手机相同的一份 **MobileNetV2 tflite模型**。Android默认离线识别，联网时可以主动选择云端单图片识别或同图对比；模型训练仍在本地4台PC完成。系统与课程材料计划于 **2026年10月14日** 完成。

仓库：<https://github.com/233zsq/mobile-cloud-object-recognition>

## 当前状态

已完成Flask、MySQL记录存储、UUID去重、修订号纠错、分页查询、统计和类别接口，以及每5秒刷新的Web统计页。非空API_TOKEN启用Flask与Nginx两层Bearer认证。当前默认 `campus-evolve-v3` 增加类别外范围判断，安卓本地与云端均可选择 v2/v3；不确定结果须人工确认后保存，统计页可筛选。真实云端、独立CPU运行时和Android模拟器已验证，见 [v3模型与交接记录](docs/open-set-recognition.md)。照片审核工作台已迁移到 <https://fieldnotes.bigdogaaa.cn/review/>（旧 8443 入口 308 跳转）。真实手机业务联调、真机性能及独立实拍评估仍待验收。初始化见 [后端说明](backend/README.md) 和 [数据库说明](database/README.md)，运维见 [部署说明](deploy/README.md)，接口见 [API说明](docs/api/README.md)。

手机、平板和PC可打开 [识别网页版](https://fieldnotes.bigdogaaa.cn/ios/)，使用同版云端模型；支持照片预览、记录筛选、纠错补传和本机备份。网页与审核站使用公开 HTTPS 证书，正式域名已在页脚展示 ICP 备案号。网页版实现和边界见 [使用说明](web/ios/README.md)。

维护入口已统一：实验报告、清单 I/O、版本配置分发及项目检查分别使用公共实现；Web 按状态、网络、存储、业务和视图拆分。审核站的工厂、路由、服务、CLI 和 AI 判断策略也已分开，见 [审核站模块说明](review/README.md#模块职责)。原命令、URL、类别/模型身份、记录修订和审核租约按兼容基准检查。

2026-10-14 审核站新结构已部署，服务器和本地各 148 项测试通过，公网 HTTPS、安全会话和访问边界验收通过，见 [部署证据](tests/evidence/review-refactor-deployment-20261014.json)。

## 技术栈

| 模块 | 采用的技术 | 职责 |
| --- | --- | --- |
| 本地训练 | Python、TensorFlow/Keras、预训练MobileNetV2 | 10类迁移学习、分阶段调参、评估与导出 |
| Android | Kotlin、CameraX、tflite/LiteRT、Room | 拍照、离线推理、纠错、记录、云端调用与补传 |
| 云端服务 | Flask、SQLAlchemy、PyMySQL、MySQL | 记录接收、纠错、去重、统计与单图片推理接口 |
| 云端模型 | LiteRT Python运行时、同版FP32 tflite、CPU | 加载模型并返回分类结果及分阶段耗时 |
| Web与部署 | HTML/CSS/JavaScript、Gunicorn、Nginx、systemd | 每5秒刷新统计；HTTPS、服务运行与重启 |

云端使用已有2核4GB实例，从一个Gunicorn worker和受控推理并发开始，实测资源后调整；训练在PC进行。训练环境与后端运行环境分别管理，版本以 [环境清单](docs/environment.md) 为准。

## 项目结构

```text
mobile-cloud-object-recognition/
├── android/             # Kotlin Android App：拍照、推理、本地保存与同步
│   └── app/src/main/    # java/、res/、assets/models/
├── backend/             # Flask入库、去重、纠错、查询、统计及CPU推理
├── web/                 # 原生 ES 模块统计页和云端识别页
│   ├── assets/          # css/、js/dashboard/、images/
│   └── ios/             # 识别页、modules/ 与可信运行文件清单
├── ml/                  # TensorFlow/Keras：训练、评估与 tflite 导出
│   ├── configs/         # 训练配置示例
│   └── src/recognition/ # 采集、训练、评估、报告及共用清单 I/O
├── shared/              # 按版本固定的类别、模型契约与策略分发清单
├── data/                # 原始照片、处理产物、样本清单与固定划分
├── models/              # 模型交接说明与版本元数据
│   └── releases/        # 模型发布包的本地存放位置
├── experiments/         # 实验记录模板、日志、检查点与报告
├── database/            # MySQL 建表文件与初始化数据
│   ├── schema/
│   └── seeds/
├── deploy/              # 腾讯云部署，Nginx/systemd 配置、证书及验收脚本
├── tests/               # 系统联调、验收记录与测试证据
├── scripts/             # 数据、配置、报告、统一检查、备份与交付入口
├── tools/               # 配置分发、项目检查、备份、静态打包和素材工具
├── review/              # 独立照片审核工作台、测试和发布工具
│   └── campus_review/   # factory、routes/、services/、cli/、AI 策略与任务
├── .github/workflows/   # 跨平台契约、组件测试与部署边界检查
├── docs/                # 计划、接口、模型契约、报告、PPT 与演示资料
├── .env.example         # 环境变量示例，无真实凭据
├── .gitignore           # 忽略密钥、本地配置、照片、权重与构建产物
└── CONTRIBUTING.md      # 分支、提交与模块交接规则
```

空目录用 `.gitkeep` 保留，加入实际文件后可以删除对应占位文件。

`backend/`中的Python应用位于 `app/`，本地启动入口为 `python -m app`，生产WSGI入口为 `wsgi:app`。原有Java目录仅为初始化占位，不参与Python运行，见 [后端说明](backend/README.md)。

从仓库根目录执行 `python scripts/check-project.py` 运行配置、报告、数据与 Web 核心检查。后端、审核、ML 和部署检查使用 `--group` 指定并在相应环境执行，见 [测试说明](tests/README.md)。

## 识别模式与统计口径

- **默认离线**：手机加载模型并识别，Room保存结果，联网后同步记录；云端不可用不影响该流程。
- **主动云端识别**：用户发起照片上传，`POST /api/infer`使用同版模型返回预测、置信度、版本、哈希和耗时。照片默认处理后释放，不自动进入训练样本库。
- **端云对比**：相同图片、模型、标签和预处理下比较分类结果与耗时。分别报告纯推理、预处理加推理和手机请求至返回的总等待时间，并记录设备、网络、CPU、内存与失败率。
- **采集只计一次**：推理接口不自动入库；用户采用的结果通过`POST /api/records`保存一次，来源记为`device`或`cloud`。同图对比结果进入实验记录，不重复增加日常采集总数。

云端模型部署及单图片接口纳入本期交付；自动选择模式、在线模型更新、重训调度和量化对比属于后续扩展。相同模型的部署位置不意味着准确率必然提高。

## 分工

| 角色 | 主责目录 | 交付重点 |
| --- | --- | --- |
| 组长兼测试负责人 | `tests/`、`docs/` | 进度、独立评估、端云耗时与资源对比、报告与答辩 |
| 模型训练负责人 | `ml/`、`models/`、`experiments/` | 训练、调参、转换、端云同版模型与一致性 |
| Android 开发负责人 | `android/` | CameraX、端侧推理、云端调用、Room、纠错与补传 |
| 数据与云端负责人 | `backend/`、`web/`、`database/`、`deploy/`、`data/` | 样本、Flask接口、CPU模型部署、数据库与统计页 |

已有项目分工和开发计划书的原文件副本保存在本地 `docs/planning/`，不随公开仓库同步；资料位置说明见 [规划资料](docs/planning/README.md)。

## 开发顺序

1. 阅读 [协作说明](CONTRIBUTING.md)，各自在功能分支开发。
2. 在 [环境清单](docs/environment.md) 登记并统一验证后的工具和依赖版本。
3. 按已冻结的 [类别映射](shared/README.md)、[接口约定](docs/api/README.md) 与 [模型交接要求](docs/model-contract.md) 开发；变更另设版本并保留历史身份。
4. 按各模块 README 使用现有 Android、Flask、审核站和训练工程，分别准备依赖环境；云端与 Android 核对同版发布包。
5. 使用统一检查入口完成相关组件回归；网页整体发布所有运行模块，审核站使用完整源码归档，服务器升级保留备份与旧发布。
6. 按实际证据维护`tests/acceptance-cases.csv`，补齐真机业务联调、独立实拍评估、端云耗时及资源测试和课程材料。

| 日期 | 主要检查点 |
| --- | --- |
| 10月8日 | 真机离线推理、Flask接收接口与输入/标签检查 |
| 10月9日 | 原始样本和固定划分、首版10类模型 |
| 10月10日 | 离线识别到Web主链路；云端同版CPU模型可加载 |
| 10月11日 | 单图片推理、端云模型、纠错和补传完成；基础功能冻结 |
| 10月12日至14日 | 独立评估、端云耗时及资源测试、修复、材料与交付 |

原始照片、模型权重与训练检查点存放在对应本地目录并另行备份；Git 跟踪代码、清单、配置和经过整理的实验结论。具体规则见各目录说明。
