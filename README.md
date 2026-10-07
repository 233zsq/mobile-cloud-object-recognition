# 移动端物品图像采集与识别系统

计算机系统项目综合实践：手机拍照，在 Android 端离线识别物品，再把识别记录同步到云端，由 Web 页面展示统计结果。

仓库：<https://github.com/233zsq/mobile-cloud-object-recognition>

## 当前状态

本仓库目前完成目录初始化、协作约定与资料归档。各模块是待开发的目录骨架，尚未生成 Android Gradle 工程、Spring Boot 工程或训练程序，也没有模型、APK、运行结果或已通过的验收记录。依赖版本由各负责人验证后统一登记。

## 项目结构

```text
mobile-cloud-object-recognition/
├── android/             # Java Android App：拍照、推理、本地保存与同步
│   └── app/src/main/    # java/、res/、assets/models/
├── backend/             # Spring Boot：结果接收、纠错、查询与统计
│   └── src/             # main/java、main/resources、test/java
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
├── deploy/              # 腾讯云部署，预留 Nginx 与 systemd 配置
├── tests/               # 系统联调、验收记录与测试证据
├── scripts/             # 后续数据检查、备份与交付辅助脚本
├── docs/                # 计划、接口、模型契约、报告、PPT 与演示资料
├── .env.example         # 环境变量名称草案，无真实凭据
├── .gitignore           # 忽略密钥、本地配置、照片、权重与构建产物
└── CONTRIBUTING.md      # 分支、提交与模块交接规则
```

空目录用 `.gitkeep` 保留，加入实际文件后可以删除对应占位文件。

## 分工

| 角色 | 主责目录 | 交付重点 |
| --- | --- | --- |
| 组长兼测试负责人 | `tests/`、`docs/` | 进度、独立评估、真机性能、报告与答辩 |
| 模型训练负责人 | `ml/`、`models/`、`experiments/` | 训练、调参、转换、模型交接 |
| Android 开发负责人 | `android/` | CameraX、端侧推理、Room、纠错与补传 |
| 数据与云端负责人 | `backend/`、`web/`、`database/`、`deploy/`、`data/` | 样本清单、云端、统计页与部署 |

已有项目分工和开发计划书的原文件副本保存在本地 `docs/planning/`，不随公开仓库同步；资料位置说明见 [规划资料](docs/planning/README.md)。

## 开发顺序

1. 阅读 [协作说明](CONTRIBUTING.md)，各自在功能分支开发。
2. 在 [环境清单](docs/environment.md) 登记并统一验证后的工具和依赖版本。
3. 冻结 [类别映射](shared/README.md)、[接口草案](docs/api/README.md) 与 [模型交接约定](docs/model-contract.md)。
4. 各负责人分别在 `android/` 生成 Java Android 工程，在 `backend/` 生成 Spring Boot 工程，在 `ml/` 建立训练环境与入口。各模块 README 说明预留目录用途。
5. 先用小样本跑通模型转换与手机加载，再实现手机上报、云端入库和网页展示。
6. 完成纠错、断网补传与 UUID 去重后，冻结版本并填写 `tests/acceptance-cases.csv`，整理独立评估与课程材料。

原始照片、模型权重与训练检查点存放在对应本地目录并另行备份；Git 跟踪代码、清单、配置和经过整理的实验结论。具体规则见各目录说明。
