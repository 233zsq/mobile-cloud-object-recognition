# COCO 2017＋实拍测试集

本测试集用于最终模型测试，不用于训练、早停、阈值选择或模型选择。保留现有训练/验证划分，测试前先冻结模型、阈值和测试清单。不得根据预测正确与否挑选、删除或替换测试照片。

该测试是 **COCO官方框裁剪图＋手机实拍图的混合分类测试**。它不是COCO目标检测评测，也不能替代全10类手机实拍验收。报告分别记录整体10类分类指标、COCO来源准确率和实拍来源准确率，不将混合成绩填写为 `independent_field_accuracy`。

| 来源 | 项目类别 | 目标 |
|---|---|---|
| COCO val2017官方实例标注 | 水杯、伞、书本、鼠标、键盘、背包 | 每类20张，共120张 |
| 手机实拍 | 笔袋、耳机、充电器、钥匙 | 每类20张，共80张 |

类别口径采用 `campus-10-v4`，包括笔记本内置键盘和遮阳伞，标签索引保持0～9。实拍每类尽量选择至少5件不同实物，每件约4张，覆盖背景、角度和光线；实物及拍摄场次必须与训练/验证数据隔离。

## 固定抽样与隔离

- 从官方 `instances_val2017.json` 读取类别和目标框；固定文件SHA-256为 `e8c7f7908f1d7278341fae127d0da654f102f11bd7b21d8aeefa635b8c810b6f`。
- 种子42；非crowd目标，框短边至少48像素、框面积至少占原图1%；每张原图只选一个目标。按框向外扩展5%后裁剪，保留原始像素，不预先放大；部署预处理仍使用现有224×224规格。
- 优先分配较稀缺的类别，固定打乱顺序。先排除与已有训练/验证、采集清单和其他测试预留集的身份、SHA-256及感知哈希冲突；数量不足如实报告，不复制样本凑数。
- 保存原图、裁剪图、来源ID、官方框、许可、原图和裁剪图哈希。下载仅限所选照片，不下载完整1GB图片ZIP；原始注释通过官方ZIP范围读取，约6.6MB。
- `data/test-reservations/<版本>/samples.csv` 是测试预留清单。训练/验证加载、分组冻结和增量导入会检查其身份，预留照片及原图、近重复图不能流入开发数据。训练检查只读取身份清单，不打开测试图片。
- 初始状态为待视觉核对和待实拍。核对只能检查类别、目标框与图片可用性；只有全部确认、四类实拍齐全后才能冻结。不得送入网站的训练审核批次。

## 准备与冻结

先安装训练模块，在实际照片所在根目录执行；代码和照片存储分离时设置 `RECOGNITION_ROOT` 为照片根目录。

```text
python -m recognition testset prepare-coco --version campus-coco-test-v1
```

输出预留清单、来源和抽样元数据，以及 `data/processed/coco-test/campus-coco-test-v1/class-<索引>-contact.jpg` 六张预览图。保留原清单不动，复制为审核清单后仅修改 `review_status`、`review_reason`。四类实拍按同样CSV字段填写，`source_dataset=field`，必须提供 `object_id`、`session_id`、正确类别、照片路径和SHA-256。模板位于预留目录的 `field-template.csv`。

官方标注与本项目口径不符或目标不可辨认时，记录视觉拒绝原因，在模型测试前补选新样本。保留原预留版本和完整审核决定，使用新版本接续；已确认的样本保留，拒绝原图不重复抽取，抽样规则和种子不变：

```text
python -m recognition testset prepare-coco --version campus-coco-test-v2 --replace-reservation campus-coco-test-v1 --reviewed-manifest reviewed-coco.csv
```

补选入口检查历史测试记录，已经用于模型测试的照片不能再补选替换。补选只修正数据标注与可用性问题，不以模型预测结果作为依据。

```text
python -m recognition testset freeze-mixed --version campus-mixed-test-v1 --reservation campus-coco-test-v1 --reviewed-manifest reviewed-coco.csv --field-manifest field-four-classes.csv --training-version campus-evolve-data-v1
```

冻结要求全部200张视觉审核通过，6类COCO各20张、4类实拍各20张；类别版本与开发数据一致，图片可读且哈希不变，训练/验证隔离通过。缺图时只交付预留集和缺口，不运行不完整的正式测试。

## 模型选定后的测试

```text
python -m recognition evaluate --release models/releases/<选定模型版本> --split test --test-version campus-mixed-test-v1 --confirm-model-hash <已冻结模型SHA256>
```

保存准确率、宏平均F1、10类指标、10×10混淆矩阵、错误样例和按来源统计，以及模型/标签/测试清单/原图/裁剪图哈希。不改写发布包的手机实拍验收字段。第一次测试记录不可覆盖；更换模型不能通过更名版本或重新裁剪原图复用已使用的测试照片。若据此改进模型，原测试只能作为历史诊断证据，后续最终验收须准备新的独立测试数据。

来源：[COCO官方下载与API说明](https://cocodataset.org/#download)、[官方类别示例](https://github.com/cocodataset/cocoapi/blob/master/PythonAPI/pycocoDemo.ipynb)。

## 2026-10-10准备记录

当前选定的COCO预留版本是 `campus-coco-test-v4`，6类各20张，共120张、120个不同源图片ID。初次抽样后经过三次视觉补选，共替换22张口径不符或目标不可辨认的照片；v1～v4及逐张决定均保留。核对由Codex辅助视觉检查完成，不代表独立人工专家一致性评估，未运行任何模型预测。后续冻结应引用v4和它的 `visual-reviewed.csv`。

下载原始照片累计约21.6MB，官方验证标注采用范围读取约6.6MB。没有下载完整COCO图片包，也没有消耗Qwen审核额度。COCO元数据没有提供逐图作者姓名，保留其原始Flickr地址和许可，不虚构作者。

四类实拍仍缺各20张，共80张；完整测试未冻结、未运行。手机实拍验收和模型发布批准状态保持待完成。
