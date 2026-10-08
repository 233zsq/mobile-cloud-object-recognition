# 移动端物品图像采集与识别系统

计算机系统项目综合实践：手机拍照，在 Android 端离线识别物品，再把识别记录同步到云端，由 Web 页面展示统计结果。

后端采用 **Python Flask**，云端部署与手机相同的一份 **MobileNetV2 tflite模型**。Android默认离线识别，联网时可以主动选择云端单图片识别或同图对比；模型训练仍在本地4台PC完成。系统与课程材料计划于 **2026年10月14日** 完成。

仓库：<https://github.com/233zsq/mobile-cloud-object-recognition>

## 当前状态

当前工作区已建立Flask工程、MySQL四张核心表，以及记录上传、UUID去重和内容冲突保护，并在腾讯云完成Gunicorn、Nginx、自签名HTTPS和代理层Bearer认证部署，公网记录接口已验证。查询、纠错、统计、Web、应用自身鉴权和云端模型仍待接入；Android与模型功能分支整体成果尚未集成，尚无完整系统验收。数据库初始化与启动见 [后端说明](backend/README.md) 和 [数据库说明](database/README.md)，服务器运维见 [部署说明](deploy/README.md)，版本见 [环境清单](docs/environment.md)。

## 技术栈

| 模块 | 计划采用的技术 | 职责 |
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
├── backend/             # Flask记录入库与去重已实现；查询、纠错、统计、推理待接入
├── web/                 # HTML/JavaScript 统计页，计划每 5 秒刷新
│   └── assets/          # css/、js/、images/
├── ml/                  # TensorFlow/Keras：训练、评估与 tflite 导出
│   ├── configs/         # 训练配置示例
│   └── src/recognition/ # 待实现的 Python 模块
├── shared/              # 跨模块类别约定与类别清单草案
├── data/                # 原始照片、处理产物、样本清单与固定划分
├── models/              # 模型交接说明与版本元数据
│   └── releases/        # 模型发布包的本地存放位置
├── experiments/         # 实验记录模板、日志、检查点与报告
├── database/            # MySQL 建表文件与初始化数据
│   ├── schema/
│   └── seeds/
├── deploy/              # 腾讯云部署，Nginx/systemd 配置、证书及验收脚本
├── tests/               # 系统联调、验收记录与测试证据
├── scripts/             # 后续数据检查、备份与交付辅助脚本
├── docs/                # 计划、接口、模型契约、报告、PPT 与演示资料
├── .env.example         # 环境变量名称草案，无真实凭据
├── .gitignore           # 忽略密钥、本地配置、照片、权重与构建产物
└── CONTRIBUTING.md      # 分支、提交与模块交接规则
```

空目录用 `.gitkeep` 保留，加入实际文件后可以删除对应占位文件。

`backend/`中的Python应用位于 `app/`，本地启动入口为 `python -m app`，生产WSGI入口为 `wsgi:app`。原有Java目录仅为初始化占位，不参与Python运行，见 [后端说明](backend/README.md)。

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
3. 冻结 [类别映射](shared/README.md)、[接口草案](docs/api/README.md) 与 [模型交接约定](docs/model-contract.md)。
4. 在`android/`生成Kotlin Android工程，在`backend/`建立Flask应用与独立Python环境，在`ml/`建立训练入口；云端模型使用同一发布包。
5. 先跑通小样本转换和真机加载，完成Flask记录接收、MySQL入库及Web展示，再接入云端CPU模型与单图片接口。
6. 完成主动云端调用、纠错、补传和UUID去重，10月11日晚冻结基础功能；随后填写`tests/acceptance-cases.csv`，完成独立评估、端云对比、回归与材料。

| 日期 | 主要检查点 |
| --- | --- |
| 10月8日 | 真机离线推理、Flask接收接口与输入/标签检查 |
| 10月9日 | 原始样本和固定划分、首版10类模型 |
| 10月10日 | 离线识别到Web主链路；云端同版CPU模型可加载 |
| 10月11日 | 单图片推理、端云模型、纠错和补传完成；基础功能冻结 |
| 10月12日至14日 | 独立评估、端云耗时及资源测试、修复、材料与交付 |

原始照片、模型权重与训练检查点存放在对应本地目录并另行备份；Git 跟踪代码、清单、配置和经过整理的实验结论。具体规则见各目录说明。
