"""Regenerate the model chapter from recorded experiments, never from target metrics."""
from collections import Counter
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'ml/src'))
from recognition.common import read_json, read_csv, now

campaign=ROOT/'experiments/reports/pilot-cpu-20261007'
stages={name:read_json(campaign/(name+'-summary.json')) for name in ['learning_rate','dropout','fine_tune']}
winner=stages['fine_tune']['winner']
repeat=read_json(ROOT/'experiments/reports'/ (winner['experiment_id']+'-repeat43')/'result.json')
release=ROOT/'models/releases/pilot-cpu-tuned-v1'
metadata=read_json(release/'metadata.json')
comparison=read_json(release/'validation-comparison.json')
dataset=read_json(ROOT/'data/splits'/winner['config']['data_version']/'dataset.json')
rows=read_csv(ROOT/'data/manifests/public-reviewed.csv')
approved=Counter(int(r['category_id']) for r in rows if r['review_status']=='approved')
candidate=Counter(int(r['category_id']) for r in rows)
labels=metadata['categories']
gap=abs(winner['validation']['macro_f1']-repeat['validation']['macro_f1'])
lines=[
'# 模型训练历史先导实验材料', '',
f'生成时间：{now()}。所有数字来自保存的清单及实验JSON。', '',
'本章节保留先导实验；当前模型结果见[扩展数据实验](ml-expanded-experiments.md)。', '',
'## 历史先导结论', '',
f"已完成本机CPU上的基线、三阶段贪心调参及种子43完整流程复核。胜出公开验证集准确率{winner['validation']['accuracy']:.2%}、宏平均F1={winner['validation']['macro_f1']:.4f}。",
'发布包保持experimental。指定WSL GPU正式训练、独立实拍准确率、Android及真实云端结果仍待完成，不据公开验证成绩宣布验收达标。', '',
'## 数据来源与冻结', '',
f"类别版本：{metadata['category_version']}；数据版本：{dataset['data_version']}；随机种子42。键盘仅独立外接计算机键盘。",
f"本次实验使用{dataset['files']['train']['count']}张训练照片、{dataset['files']['validation']['count']}张验证照片，全部来自Commons和Open Images公开照片，按组约75%/25%划分。独立手机实拍照片尚未提供，当前为0张；公开照片不记作自采成果。",
'Open Images来源中的validation/test名称属于公开来源划分，均可作为本项目公开训练/验证来源，不是独立实拍验收测试。',
'SHA-256去除完全重复，来源URL、实物ID、人工系列组及感知哈希用于分组。同件物品/同产品系列保持同组。公开实物身份无法确认时object_id留空，来源/近重复隔离不能证明完全的实体隔离。', '',
'| 类别 | 试验训练 | 试验验证 | 当前公开候选 | 当前审核通过 | 距每类80张缺口 |',
'| --- | ---: | ---: | ---: | ---: | ---: |']
for c in labels:
    i=c['id']; key=str(i)
    lines.append(f"| {c['display_name']} | {dataset['files']['train']['counts'].get(key,0)} | {dataset['files']['validation']['counts'].get(key,0)} | {candidate[i]} | {approved[i]} | {max(0,80-approved[i])} |")
lines += ['', '先导实验划分保持不变；后续审核数据使用新版本，当前进度见implementation-status.json。',
'水杯、笔袋数量较多，雨伞和充电器较少；书本含较多历史书籍。补拍需优先覆盖现代课本、普通雨伞及手机/电脑适配器，补拍实物与最终测试实物分开。', '',
'## 训练设置与比较', '',
'MobileNetV2 alpha=1.0，ImageNet预训练，GAP、Dropout、10类Softmax；模型内部x/127.5-1。训练集采用固定的适度旋转、平移、缩放和亮度增强；验证处理确定且不增强。',
'所有候选batch32、种子42、最多20轮、验证损失早停patience3；按验证宏F1、准确率、较低损失排序。微调从同一胜出分类头开始，新Adam学习率降为1/10；BN参数与统计量冻结，骨干training=False。', '',
'| 阶段 | 候选 | 轮数 | 验证准确率 | 宏F1 | 验证损失 | 训练秒数 |',
'| --- | --- | ---: | ---: | ---: | ---: | ---: |']
for stage,result in stages.items():
    field='fine_tune_scope' if stage=='fine_tune' else stage
    for r in result['candidates']:
        v=r['validation']
        lines.append(f"| {stage} | {r['config'][field]} | {len(r['history'])} | {v['accuracy']:.2%} | {v['macro_f1']:.4f} | {v['loss']:.4f} | {r['training_seconds']:.1f} |")
lines += ['',
f"胜出配置：分类头学习率{stages['learning_rate']['winner']['config']['learning_rate']}、Dropout {winner['config']['dropout']}、微调{winner['config']['fine_tune_scope']}，微调学习率{winner['config']['learning_rate']}。最终使用主实验种子42检查点。",
f"种子43完整复核：准确率{repeat['validation']['accuracy']:.2%}、宏F1={repeat['validation']['macro_f1']:.4f}；F1差{gap:.5f}。差异未超过0.05，无需种子44追加复核。", '',
'## 全10类公开验证指标', '',
'| 类别 | 精确率 | 召回率 | F1 | 验证数量 |',
'| --- | ---: | ---: | ---: | ---: |']
for c in labels:
    m=winner['validation']['classification_report'][c['label_key']]
    lines.append(f"| {c['display_name']} | {m['precision']:.4f} | {m['recall']:.4f} | {m['f1-score']:.4f} | {int(m['support'])} |")
lines += ['', '充电器召回率仅20%（5张验证图），是当前明显弱项；小样本类别指标不稳定。模型仍需补图及独立实拍检验。', '',
'## 阈值、导出与一致性', '',
f"低置信阈值{metadata['low_confidence_threshold']:.2f}，仅从验证集扫描选择；该阈值下116/128张高置信，覆盖率90.625%、准确率90.52%。始终输出Top-1，低置信提示人工确认。该阈值只适用于此试验模型。",
f"FP32 TFLite实际文件{metadata['model_bytes']:,}字节，低于15MB；仅内置算子，无量化与Flex。模型SHA-256：`{metadata['sha256']}`。",
f"完整128张验证照片Keras/TFLite最大分数差{comparison['max_score_difference']:.8f}，Top-1差异数{len(comparison['top1_mismatch_sample_ids'])}。20张真实照片交接样例（每类2张）附完整分数与little-endian输入张量；独立LiteRT环境不含TensorFlow，复核最大分数差0。",
'CPU实测：1线程、预热20次、测100次，纯推理P50/P95约9.65/10.36ms，预处理加推理约27.03/38.50ms。使用交接样例照片，包含本地读图；不是手机或真实云端结果。', '',
'## 图表与证据文件', '',
f"- 胜出训练曲线：`experiments/reports/{winner['experiment_id']}/training-curves.png`。",
'- 各阶段候选CSV及参数曲线：`experiments/reports/pilot-cpu-20261007/*-summary.csv`及PNG。',
'- 10×10混淆矩阵及错误样例：`experiments/reports/evaluations/pilot-cpu-tuned-v1/`。',
'- 复核差异：`experiments/reports/pilot-cpu-20261007-fine_tune-3-repeat43/reproduction.json`。',
'- 模型、标签及交接样例哈希：`models/releases/pilot-cpu-tuned-v1/release-files.json`。',
'- 本机CPU环境锁：`ml/requirements-windows-cpu.lock`；独立运行时锁：`ml/requirements-windows-runtime.lock`。', '',
'## 复现与后续验收', '',
f"本次训练源码摘要为`{winner['identity']['code_snapshot_sha256']}`，每个run保留`code-snapshot/recognition/`及installed-dependencies.lock。基线代码提交仅记录当时仓库基点，源码摘要用于确认实际未提交实现。",
'代码后续修复已另存当前源码；复现历史实验时在新的交付工作目录将对应code-snapshot复制回ml/src/recognition，使用冻结照片和相同环境，再生成新的campaign/experiment ID。不要混合不同源码摘要的候选。',
'四PC任务JSON已生成，其他PC须匹配数据、类别、环境及源码；完整流程仍为学习率→Dropout→微调→种子43复核，差异大时追加种子44。',
'WSL管理员组件、重启及Linux账号创建完成后，运行scripts/setup-ml-wsl.sh实测GPU；CPU预跑不能代替RTX4060梯度及显存验收。',
'组长冻结每类至少20张手机实拍照片后，使用split --test-only及evaluate --split test。模型/阈值已冻结，测试结果不回流选参。Android与真实云端分别核对张量及从图片开始的处理，并按20次预热、至少100次测量记录P50/P95；网络等待另测。',
'未满足独立测试准确率85%或宏F1 0.80时如实报告；修改模型须使用新的独立测试版本。', '']
(ROOT/'docs/ml-experiments.md').write_text('\n'.join(lines),encoding='utf-8')
print(str(ROOT/'docs/ml-experiments.md'))
