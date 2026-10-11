# 笔袋商品图纳入训练

2026年10月11日，57张笔袋商品图审核和抽检完成后，冻结为服务器批次004，导入独立数据版本 `campus-evolve-data-v3`。43张加入训练、14张加入开发验证；笔袋累计161张训练、55张验证。全部10类累计1,850张训练、623张验证，共2,473张原图。

逐张完成解码、SHA-256、审核裁剪、来源组及感知哈希检查。本批没有裁剪，形成57个来源/近重复连通组，未发现重复、标签冲突、跨集合组冲突或预留测试身份重叠。原 `campus-evolve-data-v2` 的2,416张照片及训练/验证归属全部保留，旧清单和获批父模型的文件哈希未改变。实物身份未知的商品图仍受来源分组能力限制。

服务器冻结前已备份审核数据库；沿用站点的抽检、标签和文件哈希保护，并记录用户授权的代操作来源。原服务器归档与本地重组归档分别保存哈希。本地组包使用缓存的原图，没有从服务器重新下载照片。

商品图标为 `web_product`，保存商品页、原图地址及审核溯源；许可仍为未确认。照片审核通过只表示可用于图像实验，不能作为版权授权证明。原图、批次包和含账号信息的审核快照保留在本地交付目录与受限服务器中。

新候选使用实验名 `campus-evolve-v3-seed42`，从已经人工批准的 `campus-evolve-v1` 检查点开始，保持与v2相同的MobileNetV2、最后1块微调、学习率0.0001、Dropout 0.4、batch 32、最多20轮、验证损失早停3轮，52层BN冻结。种子43从同一父检查点完整复核；宏平均F1差异超过0.05时补充种子44。每轮保存模型和优化器状态，23:00前保存停止。新模型仍需人工批准发布。

v2训练结果继续保留作对照。比较两版时先在同一批旧验证照片（609张）上比较整体和笔袋指标；新增加的14张商品验证照片单列结果，不能直接把623张与609张的总分当作同条件比较。COCO预留测试照片及尚待采集的独立实拍不参与训练、选参和阈值选择。公开开发验证结果不代表手机实拍验收。

冻结清单在 `data/splits/campus-evolve-data-v3/`，配置在 `ml/configs/generated/campus-evolve-data-v3.json`，整理证据在 `experiments/reports/evolution/campus-evolve-data-v3-evidence.json`。本地完整交付位于 `ml-deliveries/campus-evolve-data-v3/`。

已有环境可使用统一入口训练和复核；新环境需先恢复原图、获批父模型及检查点，并保持冻结清单的原始字节：

```bash
python -m recognition train --config "$RECOGNITION_ROOT/ml/configs/generated/campus-evolve-data-v3.json" --experiment campus-evolve-v3-seed42
python -m recognition reproduce --result "$RECOGNITION_ROOT/experiments/reports/campus-evolve-v3-seed42/result.json" --seed 43
```

Windows工作树从WSL使用时，应将 `GIT_DIR` 指向对应的WSL Git元数据目录，`GIT_WORK_TREE` 指向源码目录，确认 `git rev-parse HEAD` 成功再启动训练；否则Linux Git无法解析工作树文件中的Windows绝对路径，训练记录的代码提交会不可用。
