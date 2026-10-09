# campus-evolve 人工迭代流程

用户已确认保留 `campus-gpu-v1` 作为固定基准，建立 `campus-evolve-v1` 新系列：人工审核、批次GPU训练、人工批准发布。原877张公开照片、659/218固定划分、模型和本地备份保持原样。新系列首个真实候选要等新增照片审核完成，当前没有新模型准确率或提升结论。

## 数据和训练

云端审核台见 [review/README.md](../review/README.md)。冻结批次只用于训练和开发验证，不接收正式独立测试图。每件实物统一ID，系列/近重复统一组；下载批次包后先核验归档及逐图哈希，再导入。

2026年10月9日确认键盘包括笔记本内置键盘，新审核批次使用 `campus-10-v3`，标签ID与顺序不变。基准数据、模型及类别v2文件保持原始身份；导入仅允许已确认的v2→v3范围扩大，保存类别迁移记录，从旧基准权重开始训练。原公开验证照片归属不改，比较报告单独提示口径扩大，不能把旧成绩解释为已覆盖新增场景。此前因“内置键盘”被拒的未冻结照片需人工重新审核，不自动批准。

导入保留基准数据中每张照片原有训练/验证归属，仅对新增独立组按约75%/25%划分。新照片关联旧训练组时归训练，关联旧验证组时归验证，连接两者则拒绝；近重复跨集合也拒绝。单类只有一个独立新组时全部归训练，不能据此声称实拍验证改善。正式测试清单仅用于比对身份，导入和训练不会读测试图片。

批次也可包含经人工重新审核的 Commons/Open Images 网图，来源、作者、许可及下载版本随清单保留。可选框选仅裁剪训练主体，原图继续存档。导入先验原始字节，再在EXIF纠正后的坐标中裁剪，重新计算训练照片哈希与感知哈希；同时保留原图哈希、原图感知哈希及来源样本ID，统一参与分组、旧划分归属及独立测试隔离。原图与裁剪的关系不能通过改组名解除，裁剪不计作新的独立原始照片。与旧组标签矛盾的候选须重新审核。

仍使用MobileNetV2和冻结十类别顺序。首轮默认从基准 `.keras` 检查点开始，Dropout0.4、学习率0.0001、最后一块、batch32、最多20轮、耐心3、停止时间23:00。Dropout须与父检查点一致；其他参数可在首次训练前调整并保存，修改后用新实验ID。不使用原ImageNet分类头的三阶段sweep入口。

示例在训练仓库根目录执行（新源码和已有大文件在同一仓库时）：

```bash
export ML_TRAIN_ENV=/opt/campus-recognition/venvs/gpu
source scripts/activate-ml-wsl.sh
python -m recognition evolve import-batch --archive /path/field-batch-001.zip --version campus-evolve-data-v1
python -m recognition train --config ml/configs/generated/campus-evolve-data-v1.json --experiment campus-evolve-v1-seed42
python -m recognition reproduce --result experiments/reports/campus-evolve-v1-seed42/result.json --seed 43
```

当前独立功能工作区位于 `ml-gpu-review`，原照片及检查点在 `mobile-cloud-object-recognition`。合并前使用新源码及原数据根：

```bash
export RECOGNITION_ROOT=/mnt/d/projects/计算机系统项目实践/mobile-cloud-object-recognition
export PYTHONPATH=/mnt/d/projects/计算机系统项目实践/ml-gpu-review/ml/src
```

命令中的配置/结果路径此时位于 `RECOGNITION_ROOT`，用绝对路径引用；Python源码提交从源码所在仓库记录，数据身份从数据根记录。
分离源码和数据根时，须将源码中的 `shared/category-versions/campus-10-v3.json` 按原字节复制到数据根的同名路径，不替换其 `shared/categories.json` 或旧冻结清单。

`parent_finetune`记录父模型版本、模型哈希、元数据哈希、检查点路径和哈希。种子42/43/44都从同一个不可变父检查点开始，新Adam和对应种子的Dropout随机状态；复核不重建ImageNet分类头。续训自动核对上述身份。宏F1差>0.05时补种子44；正式导出也核对父模型身份。

## 验证与审批

```bash
python -m recognition export --result experiments/reports/campus-evolve-v1-seed42/result.json --version campus-evolve-v1 --formal --reproduction experiments/reports/campus-evolve-v1-seed42-repeat43/result.json
python -m recognition evolve compare --release models/releases/campus-evolve-v1
```

仍执行FP32内置算子导出、≤15MB、完整验证集Keras/LiteRT对照、每类2张共20张样例和发布包哈希检查。导出的 `frozen` 表示技术包已冻结，新系列另记 `deployment_approval=pending_human_approval`。比较报告在 `experiments/reports/evolution/`，将固定原公开验证集、新增公开开发验证和新增实拍开发验证分别比较，不读取最终测试图片。缺少类别会列出实际类别支持数；固定十类宏F1对缺失类别按0计算，不与全十类实拍结果混作提升率。

将比较报告通过SSH交管理员导入：

```bash
python3 /home/ubuntu/apps/campus-review/current/review/deploy/manage.py register-candidate /path/to/campus-evolve-v1-comparison.json
```

网页显示同图指标。管理员审阅类别指标、混淆矩阵和样本量，决定批准或拒绝；系统不自动决定“新模型更好”。批准记录绑定报告及模型哈希、账号、时间和理由。下载批准JSON后在训练PC附入发布包：

```bash
python -m recognition evolve accept-approval --release models/releases/campus-evolve-v1 --receipt /path/campus-evolve-v1-approval.json --comparison experiments/reports/evolution/campus-evolve-v1-comparison.json
```

生成独立 `approval.json`，不改已冻结的模型和元数据。后续若以新系列模型为父模型，必须具有匹配模型哈希的批准记录。候选包、比较报告和批准JSON一起交给接入负责人；不会自动更换Android或现有443云端模型。

下一批导入时显式指定 `--base-version 上一数据版本`，保留累计审核照片；若从已批准的新模型继续训练，再指定 `--parent-release 上一模型版本`。导入检查数据祖先链，不能丢掉父模型已使用的数据。比较仍以固定 `campus-gpu-v1` 为基准，并验证模型祖先链。

正式实拍验收仍由组长冻结新测试版本执行。不同模型不得复用已经用于正式独立测试的照片；改版本名不能绕过照片身份保护。旧218张公开验证集属于开发比较数据，可以持续比较，但反复选参会增加对其过拟合的风险。

## 已验证与待完成

网页账号、邀请、审核并发修订、图片边界、冻结哈希、下载和人工审批已在Windows及实际Ubuntu验证；旧训练回归检查与新增父模型梯度/复核检查通过。合成网络及图片只用于测试工具链，不作为物品识别成绩。

待新增真实照片、真实新系列训练及验证、人工发布审批。独立实拍测试和Android接入继续单独完成。`campus-gpu-v1`及其历史实验材料不随新系列状态改写。
