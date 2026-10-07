"""Write the completed expanded CPU campaign's evidence-backed model chapter."""
from collections import Counter
from recognition.common import ROOT,read_json,read_csv,write_json,digest,now,categories
from recognition.training import snapshot
campaign='expanded-cpu-20261007';version='expanded-cpu-v1'
stages={s:read_json(ROOT/'experiments/reports'/campaign/(s+'-summary.json')) for s in ['learning_rate','dropout','fine_tune']}
winner=stages['fine_tune']['winner'];release=ROOT/'models/releases'/version
meta=read_json(release/'metadata.json');data=read_json(ROOT/'data/splits'/meta['data_version']/'dataset.json')
repeat=read_json(ROOT/'experiments/reports'/(winner['experiment_id']+'-repeat43')/'result.json')
gap=abs(winner['validation']['macro_f1']-repeat['validation']['macro_f1'])
comparison=read_json(release/'validation-comparison.json')
timing=read_json(ROOT/'experiments/reports/benchmarks'/version/'local-cpu-1threads.json')
evidence=read_json(ROOT/'experiments/reports/audit/final-public-data.json')
labels=categories()['categories']
lines=['# 新版公开照片模型实验材料','',f'生成时间：{now()}。只报告已保存的真实实验结果。','',
'## 结论与验收边界','',
f"数据版本{meta['data_version']}，659张公开训练、218张公开验证；新版胜出验证准确率{winner['validation']['accuracy']:.2%}、宏F1={winner['validation']['macro_f1']:.4f}。",
'本机Windows CPU完成三阶段和完整流程复核，模型保持experimental。WSL GPU正式训练、独立实拍测试、Android和真实云端验收仍待完成。',
'公开验证成绩用于选参，不能作为独立实拍准确率验收成绩。旧版514张先导实验保留在ml-experiments.md，两版划分不同，成绩不作直接提升率比较。','',
'## 数据与来源','',
f"公开候选{evidence['candidate_count']}张，审核通过{evidence['approved_count']}张、拒绝{evidence['rejected_count']}张。通过来源：{evidence['approved_by_source']}。独立手机实拍0张，公开照片不记为自采成果。",
'Commons及Open Images官方人工正标签候选均经图像审核；来源中的public-test属于公开训练/验证来源，独立实拍测试另行冻结。',
'按SHA、来源、感知哈希及人工拍摄系列分组。无法确认公开实物身份时object_id为空，分组不能证明完全实体隔离；585张早期候选的上游修订号未保留，下载版本以原始字节SHA-256标识，未虚构修订号。',
f"数据元数据SHA-256：`{digest(ROOT/'data/splits'/meta['data_version']/'dataset.json')}`。类别campus-10-v2，键盘仅独立外接计算机键盘。",
'','| 类别 | 训练 | 验证 | 公开通过 | 补拍缺口 |','| --- | ---: | ---: | ---: | ---: |']
for c in labels:
    key=str(c['id']);label=c['label_key']
    lines.append(f"| {c['display_name']} | {data['files']['train']['counts'][key]} | {data['files']['validation']['counts'][key]} | {evidence['approved_by_class'][label]} | {evidence['missing_to_80_by_class'][label]} |")
lines += ['', '877张公开训练/验证照片、约200张独立测试照片分别计数；后续126张训练/验证补拍另行计数并冻结新版本。采集规则见ml-photo-gaps.md。','',
'## 候选实验','',
'MobileNetV2/ImageNet alpha=1.0，GAP、Dropout、10类Softmax；raw RGB float32输入，模型内归一化。只有训练集增强；BN始终冻结。相同阶段初始化、冻结数据、环境及种子42。',
'本机顺序执行候选，四PC任务配置保存在campaign/pc-tasks。按宏F1、准确率、较低损失、较小微调范围及候选顺序选择。每轮原子保存模型/优化器和进度；23:00前停止长任务。','',
'| 阶段 | 候选 | 轮数 | 验证准确率 | 宏F1 | 验证损失 | 训练秒数 |','| --- | --- | ---: | ---: | ---: | ---: | ---: |']
for stage,summary in stages.items():
    field='fine_tune_scope' if stage=='fine_tune' else stage
    for r in summary['candidates']:
        v=r['validation'];lines.append(f"| {stage} | {r['config'][field]} | {len(r['history'])} | {v['accuracy']:.2%} | {v['macro_f1']:.4f} | {v['loss']:.4f} | {r['training_seconds']:.1f} |")
lines += ['',f"胜出分类头学习率{stages['learning_rate']['winner']['config']['learning_rate']}，Dropout {winner['config']['dropout']}，微调{winner['config']['fine_tune_scope']}，微调学习率{winner['config']['learning_rate']}。最终使用种子42检查点。",
f"种子43完整流程复核：准确率{repeat['validation']['accuracy']:.2%}、宏F1={repeat['validation']['macro_f1']:.4f}；宏F1差{gap:.5f}。"]
if gap>.05:
    extra=read_json(ROOT/'experiments/reports'/(winner['experiment_id']+'-repeat44')/'result.json')
    lines.append(f"差异超过0.05，已追加种子44：准确率{extra['validation']['accuracy']:.2%}、宏F1={extra['validation']['macro_f1']:.4f}；报告随机性影响，仍保留主种子42发布。")
else:lines.append('差异未超过0.05，无需追加种子44。')
lines += ['', '## 全10类验证指标','', '| 类别 | 精确率 | 召回率 | F1 | 数量 |','| --- | ---: | ---: | ---: | ---: |']
for c in labels:
    v=winner['validation']['classification_report'][c['label_key']]
    lines.append(f"| {c['display_name']} | {v['precision']:.4f} | {v['recall']:.4f} | {v['f1-score']:.4f} | {int(v['support'])} |")
lines += ['', '各类数量不同，少样本类别指标不稳定；错误预测明细、10×10混淆矩阵及错误照片单独保存。未使用实拍测试调参。','', '## 阈值、FP32与一致性','',
f"阈值{meta['low_confidence_threshold']:.2f}，状态{meta['threshold_status']}，只用验证集选择；候选支持数和准确率见winner result.json的threshold表。始终输出Top-1，低置信仅人工确认提示。",
f"FP32 TFLite实际{meta['model_bytes']:,}字节，SHA-256=`{meta['sha256']}`。转换只允许内置算子、关闭量化。",
f"完整218张验证集Keras/TFLite最大分数差{comparison['max_score_difference']:.8g}，Top-1变化{len(comparison['top1_mismatch_sample_ids'])}。20张真实交接照片、输入张量及完整分数保存在发布包examples。",
f"本机CPU单线程、20次预热/100次计时：纯推理P50/P95={timing['inference_ms']['p50']:.2f}/{timing['inference_ms']['p95']:.2f}ms；预处理加推理={timing['preprocess_and_inference_ms']['p50']:.2f}/{timing['preprocess_and_inference_ms']['p95']:.2f}ms。不是手机或真实云端性能。", '', '## 证据与复现','',
f"源码摘要：`{winner['identity']['code_snapshot_sha256']}`；每个run保留code-snapshot、installed-dependencies.lock、每轮历史、best.keras和可续训检查点。数据和类别都显式引用冻结版本。",
f"各阶段表格与参数曲线：`experiments/reports/{campaign}/`；胜出训练曲线：`experiments/reports/{winner['experiment_id']}/training-curves.png`。",
f"10×10混淆矩阵、每张预测和错误样例：`experiments/reports/evaluations/{version}/`；Keras/LiteRT比较和发布文件哈希：`models/releases/{version}/`。",
'复现命令：`python scripts/run-ml-campaign.py --config ml/configs/public-expanded-cpu.json --campaign <新ID> --version <新模型版本>`。匹配环境锁与冻结照片，不能把不同环境或源码的候选混在同一阶段。',
'完成管理员安装、重启及Ubuntu首次账号后，执行WSL脚本生成实测公共batch的GPU配置，另开GPU campaign，完成后用--formal冻结模型。',
'组长提供独立实拍清单；Android/云端按参考张量→图片完整链路核对，20次预热/至少100次计时；各项未完成就保持pending。交付及操作见ml-handover.md。','']
(ROOT/'docs/ml-expanded-experiments.md').write_text('\n'.join(lines),encoding='utf-8')
status=read_json(ROOT/'experiments/reports/implementation-status.json')
status.update(updated_at=now(),current_code_snapshot_sha256=snapshot(),trained_code_snapshot_sha256=winner['identity']['code_snapshot_sha256'])
status['training'].update(expanded_cpu_campaign='complete',expanded_winner=winner['experiment_id'],expanded_validation_accuracy=winner['validation']['accuracy'],expanded_validation_macro_f1=winner['validation']['macro_f1'],expanded_seed43_f1_difference=gap)
status['release'].update(selected=version,status=meta['status'],model_bytes=meta['model_bytes'],model_sha256=meta['sha256'],full_validation_max_score_difference=comparison['max_score_difference'])
write_json(ROOT/'experiments/reports/implementation-status.json',status)
print(ROOT/'docs/ml-expanded-experiments.md')
