"""Render a completed GPU campaign chapter; never change active release selection."""
import argparse
from recognition.common import ROOT, digest, now, read_json, safe_name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', required=True)
    parser.add_argument('--version', required=True)
    args = parser.parse_args()
    campaign, version = safe_name(args.campaign), safe_name(args.version)
    reports = ROOT/'experiments/reports'
    stages = {s: read_json(reports/campaign/(s+'-summary.json'))
              for s in ['learning_rate', 'dropout', 'fine_tune']}
    winner = stages['fine_tune']['winner']
    release = ROOT/'models/releases'/version
    meta = read_json(release/'metadata.json')
    if (meta['status'] != 'frozen' or meta['experiment_id'] != winner['experiment_id']
            or not winner['environment']['gpu'] or winner['environment']['tensor_float_32_enabled']):
        raise ValueError('Chapter requires the selected frozen, full-FP32 GPU release')
    data = read_json(ROOT/'data/splits'/meta['data_version']/'dataset.json')
    comparison = read_json(release/'validation-comparison.json')
    timing = read_json(reports/'benchmarks'/version/'local-cpu-1threads.json')
    runtimes = [read_json(p) for p in sorted((reports/'environment').glob(f'standalone-*{version}-*.json'))]
    if not runtimes or any(r['model_sha256'] != meta['sha256'] or r['tensorflow_installed']
                           or r['tensorflow_imported'] or any(not x['external']['passed'] for x in r['results'])
                           for r in runtimes):
        raise ValueError('Independent runtime evidence missing or incompatible')
    runtime_difference = max(c['max_score_difference'] for r in runtimes for x in r['results'] for c in x['external']['comparisons'])
    repeat = read_json(reports/(winner['experiment_id']+'-repeat43')/'result.json')
    evidence = read_json(reports/'audit/final-public-data.json')
    labels = meta['categories']
    gap = abs(winner['validation']['macro_f1']-repeat['validation']['macro_f1'])
    total = sum(r['training_seconds'] for s in stages.values() for r in s['candidates'])
    lines = ['# GPU模型训练实验材料', '', f'生成时间：{now()}。数字来自冻结清单和保存的实验记录。', '',
             '## 当前结果与验收状态', '',
             f"模型`{version}`已冻结。公开验证准确率{winner['validation']['accuracy']:.2%}、宏平均F1={winner['validation']['macro_f1']:.4f}。",
             'frozen表示模型、阈值和输入合同冻结，可以开始独立评估；不代表独立实拍及端云验收已达标。独立实拍、真实Android和腾讯云结果仍待对应成员提供。', '',
             '## 数据与类别', '',
             f"数据版本`{meta['data_version']}`：训练{data['files']['train']['count']}张、验证{data['files']['validation']['count']}张，均为公开照片。独立手机实拍当前0张，计划约200张，另行冻结，未用于选参。",
             f"审核通过{evidence['approved_count']}张：Commons {evidence['approved_by_source']['wikimedia_commons']}张，Open Images {evidence['approved_by_source']['open_images']}张；候选{evidence['candidate_count']}张，拒绝{evidence['rejected_count']}张。公开照片不记作自采成果。",
             'SHA-256、来源、感知哈希与人工系列分组用于隔离。公开照片无法确认实物时object_id为空，来源和近重复隔离不能证明完全实体隔离；585张早期候选的上游修订号未保存，以实际下载字节哈希标识版本。',
             f"类别`{meta['category_version']}`；键盘仅独立外接计算机键盘。数据元数据SHA-256：`{digest(ROOT/'data/splits'/meta['data_version']/'dataset.json')}`。", '',
             '| 类别 | 训练 | 验证 | 已审核公开图 | 补拍缺口 |', '| --- | ---: | ---: | ---: | ---: |']
    for c in labels:
        key, label = str(c['id']), c['label_key']
        lines.append(f"| {c['display_name']} | {data['files']['train']['counts'][key]} | {data['files']['validation']['counts'][key]} | {evidence['approved_by_class'][label]} | {evidence['missing_to_80_by_class'][label]} |")
    lines += ['', '训练/验证补拍缺口共126张，优先雨伞、书本、外接键盘和充电器；补拍实物与独立测试实物分开。新图使用新数据版本，不能修改本次冻结划分。', '',
              '## 训练设置与候选对照', '',
              'RTX4060 Laptop、WSL2/Ubuntu24.04、Python3.12.3、TensorFlow2.21.0、Keras3.12.1、NumPy2.1.3；实际依赖锁随交付保存。完整float32计算，TensorFloat-32关闭，所有候选batch32、种子42、最多20轮、验证损失早停3轮。',
              'ImageNet MobileNetV2 alpha=1.0、GAP、Dropout、10类Softmax，模型内部x/127.5-1；只有训练集增强。BN参数和统计量冻结，骨干training=False。阶段依次执行，按宏F1、准确率、低损失、较小微调范围及候选顺序选择。微调从相同胜出头开始，新Adam学习率为头学习率的1/10。',
              '首个真实训练轮耗时6.64秒；训练计时不含读图、检查点写入和导出。每轮保存优化器与随机状态，北京时间23:00前停止并支持续作。四PC任务保存在campaign/pc-tasks，未宣称异机实测或并行加速。', '',
              '| 阶段 | 候选 | 实际轮数 | 准确率 | 宏F1 | 验证损失 | 训练秒数 |', '| --- | --- | ---: | ---: | ---: | ---: | ---: |']
    for stage, summary in stages.items():
        field = 'fine_tune_scope' if stage == 'fine_tune' else stage
        for r in summary['candidates']:
            v = r['validation']
            lines.append(f"| {stage} | {r['config'][field]} | {len(r['history'])} | {v['accuracy']:.2%} | {v['macro_f1']:.4f} | {v['loss']:.4f} | {r['training_seconds']:.1f} |")
    lines += ['', f"九个候选记录的训练时间合计{total:.1f}秒。胜出头学习率{stages['learning_rate']['winner']['config']['learning_rate']}，Dropout {winner['config']['dropout']}，微调{winner['config']['fine_tune_scope']}，微调学习率{winner['config']['learning_rate']}；发布使用种子42最佳宏F1检查点。",
              f"种子43完整流程复核：准确率{repeat['validation']['accuracy']:.2%}、宏F1={repeat['validation']['macro_f1']:.4f}，与主实验F1差{gap:.5f}。"]
    if gap > .05:
        extra = read_json(reports/(winner['experiment_id']+'-repeat44')/'result.json')
        lines.append(f"差异超过0.05，追加种子44复核：准确率{extra['validation']['accuracy']:.2%}、宏F1={extra['validation']['macro_f1']:.4f}；随机性影响仍需报告，发布保留主种子42。")
    else:
        lines.append('F1差异未超过0.05，无需追加种子44。')
    lines += ['', '## 全10类公开验证指标', '', '| 类别 | 精确率 | 召回率 | F1 | 数量 |', '| --- | ---: | ---: | ---: | ---: |']
    for c in labels:
        v = winner['validation']['classification_report'][c['label_key']]
        lines.append(f"| {c['display_name']} | {v['precision']:.4f} | {v['recall']:.4f} | {v['f1-score']:.4f} | {int(v['support'])} |")
    confusions = sorted((count, i, j) for i, row in enumerate(winner['validation']['confusion_matrix']) for j, count in enumerate(row) if i != j and count)
    lines += ['', '少样本类别指标不稳定。错误预测明细及照片单独保存，未使用独立实拍成绩调参。']
    if confusions:
        lines.append('主要混淆：'+'；'.join(f"{labels[i]['display_name']}→{labels[j]['display_name']} {count}张" for count, i, j in reversed(confusions[-5:]))+'。')
    lines += ['', '## 阈值、导出与运行时', '',
              f"低置信阈值{meta['low_confidence_threshold']:.2f}，状态`{meta['threshold_status']}`，只用验证集选择。始终输出Top-1，低置信只提示人工确认。", '',
              '| 阈值 | 高置信数量 | 覆盖率 | 高置信准确率 |', '| ---: | ---: | ---: | ---: |']
    for item in winner['threshold']['candidates']:
        accuracy = '无样本' if item['accuracy'] is None else f"{item['accuracy']:.2%}"
        lines.append(f"| {item['threshold']:.2f} | {item['count']} | {item['coverage']:.2%} | {accuracy} |")
    lines += ['', f"FP32 TFLite实际{meta['model_bytes']:,}字节，低于15MB，只允许内置算子，关闭量化。模型SHA-256：`{meta['sha256']}`；标签SHA-256：`{meta['labels_sha256']}`。",
              f"完整验证集Keras/LiteRT最大分数差{comparison['max_score_difference']:.8g}，Top-1变化{len(comparison['top1_mismatch_sample_ids'])}；20张真实交接照片每类2张，附输入张量、分数、标签与来源。",
              f"独立LiteRT环境已完成{len(runtimes)}份系统复核，每份包括全部20张参考张量和20次图片链路，Top-1一致，最大分数差{runtime_difference:.8g}，未安装或导入TensorFlow。对应运行ID："+', '.join(f"`{r['run_id']}`" for r in runtimes)+'。',
              f"本机Linux CPU单线程、预热20次、测100次：纯推理P50/P95={timing['inference_ms']['p50']:.2f}/{timing['inference_ms']['p95']:.2f}ms，预处理加推理={timing['preprocess_and_inference_ms']['p50']:.2f}/{timing['preprocess_and_inference_ms']['p95']:.2f}ms。这不是手机或腾讯云性能。", '',
              '## 证据与复现', '',
              f"训练代码提交`{winner['code_commit']}`，源码摘要`{winner['identity']['code_snapshot_sha256']}`。每个run保留源码快照、安装依赖锁、逐轮历史、best.keras及优化器续训检查点。环境预跑及84项GPU检查见`ml-gpu-environment.md`。",
              '独立LiteRT参考张量与图片链路证据保存于environment/standalone-*及consistency目录；不安装或导入TensorFlow。Android及真实云端必须另外回传同图、设备及性能记录。', '',
              '```bash', 'source scripts/activate-ml-wsl.sh',
              'python scripts/run-ml-campaign.py --config ml/configs/wsl-campus-public-expanded-v1.json \\',
              '  --campaign <新的ID> --version <新的模型版本> --formal', '```', '',
              '匹配冻结数据、类别、代码和依赖，不合并不同环境候选。原campaign可以原命令续作；新配置或源码须使用新ID。CPU历史包与指标保持原记录，不用GPU结果改写它们。',
              '模型及阈值冻结后，组长提供独立测试清单执行评估；后续模型不能重用已评估测试照片。真实验收和交接命令见ml-handover.md。', '',
              '## 报告配图', '', f"![胜出训练曲线](../experiments/reports/{winner['experiment_id']}/training-curves.png)", '']
    for stage in stages:
        lines += [f'![{stage}候选对照](../experiments/reports/{campaign}/{stage}-summary.png)', '']
    lines += [f"![公开验证集混淆矩阵](../experiments/reports/evaluations/{version}/{meta['data_version']}-validation.png)", '']
    output = ROOT/'docs/ml-gpu-experiments.md'
    output.write_text('\n'.join(lines), encoding='utf-8')
    print(output)


if __name__ == '__main__':
    main()
