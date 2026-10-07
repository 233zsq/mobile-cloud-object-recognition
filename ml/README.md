# 模型训练与导出

负责人：模型训练负责人。采用 TensorFlow/Keras 与 MobileNetV2 迁移学习。

当前预留 `src/recognition/` 和配置示例，尚无训练代码或已安装的依赖。后续在模块内实现训练、验证评估、最终测试与 tflite 导出入口，并提交验证后的依赖清单。训练环境版本见 `docs/environment.md`。

`configs/baseline.example.json` 来自开发计划书中的基线参数，仅为配置草案，没有程序读取它。冻结类别清单后，将各入口的实际配置格式、命令和 GPU/CPU 环境写到本文件。

- 数据由 `data/manifests/`、`data/splits/` 的清单读取；划分按实物分组，增强仅用于训练集。
- 按学习率、Dropout、微调范围逐阶段比较候选；使用验证集选参，选定配置至少复核一次。
- 测试集用于冻结后的独立评估，不参与选参、阈值选择或量化校准。
- 实验元数据使用 `experiments/experiment-log.template.csv`，日志与检查点放在对应目录。
- 最终发布包放到 `models/releases/<模型版本>/`，按 `docs/model-contract.md` 交接。
