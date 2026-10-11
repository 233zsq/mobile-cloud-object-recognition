# campus-evolve-data-v2 数据整理记录

2026年10月11日完成审核收尾、逐图解码与SHA-256核对、框选裁剪复核、来源及近重复分组、测试身份隔离和固定划分。

## 冻结结果

- 本轮1,509张公开候选中，719张通过，790张拒绝；没有剩余人工疑难项、抽检项、AI异常项或运行中的审核任务。
- 通过照片来自服务器批次002（225张）和003（494张）。003由Codex按用户整理请求代为冻结，冻结前备份审核数据库，并记录操作来源；没有代替用户批准模型。
- 新增719张有效原图（Commons 607张、Open Images 112张），其中88张按已审核框选区域生成训练裁剪；裁剪不额外计作原图。
- 旧数据1,697张全部保留训练/验证归属；新增539张训练、180张验证。累计训练1,807张、验证609张，共2,416张。
- 新照片组成716个来源/身份/近重复连通组；其中1组关联旧验证组，留在验证集，其余715组独立划分。未发现跨集合分组冲突、标签冲突、完全重复或测试身份混入。

| 类别 | 新增原图 | 累计训练 | 累计验证 |
|---|---:|---:|---:|
| 水杯 | 95 | 175 | 58 |
| 伞 | 31 | 115 | 38 |
| 书本 | 88 | 197 | 66 |
| 笔袋 | 5 | 118 | 41 |
| 鼠标 | 66 | 197 | 66 |
| 键盘 | 58 | 185 | 67 |
| 耳机 | 132 | 255 | 86 |
| 充电器 | 112 | 180 | 60 |
| 钥匙 | 44 | 164 | 54 |
| 背包 | 88 | 221 | 73 |

笔袋本轮仅新增5张，不能声称该类多样性已充分改善。公开图片的实物身份通常未知，来源组和近重复检查也不能证明全部实物互异。人工审核与5%自动结果抽检不是全体标签错误率测量。

## 模型与测试边界

数据版本为`campus-evolve-data-v2`，类别版本为`campus-10-v4`，随机种子42。下一候选从已经管理员批准的`campus-evolve-v1`检查点继续训练；真实批准凭据绑定模型和比较报告哈希，已附在本地父模型包中。保持MobileNetV2、Dropout 0.4、学习率0.0001、最后1块微调、batch 32、最多20轮、早停耐心3，23:00前保存停止。

已在Ubuntu 24.04、Python 3.12.3、TensorFlow 2.21.0、Keras 3.12.1及RTX 4060 Laptop GPU环境成功加载父检查点，核对新清单哈希，确认52层BN均冻结、合成输入输出为float32的1×10有效Softmax。该加载核验没有进行梯度更新或训练，也未读取测试照片。

原218张公开验证和上一版429张验证均保留原成员，可继续单列同图比较；新的完整开发验证为609张。模型选择和低置信阈值仅用开发验证数据。

检查了现有4个COCO预留版本的清单身份（480条，含重复的历史修订身份），没有打开测试图片或进行测试预测。当前选定120张COCO照片继续预留；笔袋、耳机、充电器、钥匙各20张独立实拍仍待提供。混合测试与10类手机实拍验收分别记录。当前仅完成数据准备，尚未启动`campus-evolve-v2`训练，也没有新模型准确率结论。

## 本地交付与复现

交付目录：`ml-deliveries/campus-evolve-data-v2/`。归档`reviewed-batches-002-003.zip`为126,164,648字节，保留原图、审核标签、裁剪坐标、来源、许可和AI审核溯源。它依据服务器冻结清单和哈希一致的本地原图重新组包；本次整理没有重新下载任何照片。

服务器002归档SHA-256：`a76f8ec63b55b6d1f60e71f5204277c8d01e79894067bb0460ec76a45a7543ba`。

服务器003归档SHA-256：`b728dc9e3d854c6c5c6281bdbce66ab4dbefc4ebb30220f824852af0c3da1d6f`。

本地合并归档SHA-256：`cd3d3f1daa67bffba7866b989bde19c61941c03bd8a3f307fcbd74e141244784`。本地重组归档与服务器原归档是不同文件，分别保存哈希。

数据元信息SHA-256：`490ede277d995479b62af2cecabfb326e071391022f143f51a5c779d55b78dcc`。

训练清单SHA-256：`9f5814177a1b3d7e62431ab3de9ae2dae8e340360779ac1ea27a13c59e04b239`。

验证清单SHA-256：`54ff3df454d9a7e72965696bdf7bdbcc2bd0ef96232290ce54fe4882cc322e01`。

新环境须先还原上一版原图、检查点和获批父模型包，保持原数据与类别版本。用统一入口导入本地合并归档；现有版本已经冻结，不要重复导入覆盖：

```bash
python -m recognition evolve import-batch --archive /path/reviewed-batches-002-003.zip --version campus-evolve-data-v2 --base-version campus-evolve-data-v1 --parent-release campus-evolve-v1
```

已有本机WSL GPU环境从新源码和原数据根执行训练：

```bash
export RECOGNITION_ROOT=/mnt/d/projects/计算机系统项目实践/mobile-cloud-object-recognition
export PYTHONPATH=/mnt/d/projects/计算机系统项目实践/ml-gpu-review/ml/src
export ML_TRAIN_ENV=/opt/campus-recognition/venvs/gpu
source scripts/activate-ml-wsl.sh
python -m recognition train --config "$RECOGNITION_ROOT/ml/configs/generated/campus-evolve-data-v2.json" --experiment campus-evolve-v2-seed42
python -m recognition reproduce --result "$RECOGNITION_ROOT/experiments/reports/campus-evolve-v2-seed42/result.json" --seed 43
```

数据根存有原图、裁剪、父检查点、逐图来源和训练配置。Git只保存冻结清单、配置和验证材料；审核数据库快照与原始批准凭据留在受限服务器/本地交付目录，不将账号资料发布到仓库。训练完成后仍需验证对比、FP32导出及人工批准发布。
