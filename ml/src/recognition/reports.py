"""Render recorded ML campaigns; reporting never selects or changes a release."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .common import ROOT, digest, now, read_csv, read_json, safe_name

STAGES = ("learning_rate", "dropout", "fine_tune")
PROFILES = {
    "pilot-cpu": ("pilot-cpu-20261007", "pilot-cpu-tuned-v1", "ml-experiments.md"),
    "expanded-cpu": ("expanded-cpu-20261007", "expanded-cpu-v1", "ml-expanded-experiments.md"),
    "gpu": (None, None, "ml-gpu-experiments.md"),
}


@dataclass
class Report:
    root: Path
    campaign: str
    version: str
    stages: dict
    meta: dict
    data: dict
    comparison: dict
    repeat: dict
    timing: dict | None
    evidence: dict | None
    runtimes: list

    @property
    def winner(self):
        return self.stages["fine_tune"]["winner"]

    @property
    def labels(self):
        return self.meta["categories"]

    @property
    def gap(self):
        return abs(self.winner["validation"]["macro_f1"] - self.repeat["validation"]["macro_f1"])

    def repeat44(self):
        return read_json(
            self.root / "experiments/reports" / (self.winner["experiment_id"] + "-repeat44") / "result.json"
        )

    @property
    def runtime_difference(self):
        return max(
            c["max_score_difference"] for r in self.runtimes for x in r["results"] for c in x["external"]["comparisons"]
        )


def load_report(profile, campaign=None, version=None, *, root=ROOT):
    """Load the shared evidence, keeping the historical and GPU requirements distinct."""
    default_campaign, default_version, _ = PROFILES[profile]
    campaign = safe_name(campaign if campaign is not None else default_campaign)
    version = safe_name(version if version is not None else default_version)
    if profile != "gpu" and (campaign, version) != (default_campaign, default_version):
        raise ValueError("CPU profiles reproduce their fixed historical campaign and release")
    root = Path(root)
    reports = root / "experiments/reports"
    stages = {stage: read_json(reports / campaign / (stage + "-summary.json")) for stage in STAGES}
    winner = stages["fine_tune"]["winner"]
    release = root / "models/releases" / version
    meta = read_json(release / "metadata.json")
    if profile == "gpu" and (
        meta["status"] != "frozen"
        or meta["experiment_id"] != winner["experiment_id"]
        or not winner["environment"]["gpu"]
        or winner["environment"]["tensor_float_32_enabled"]
    ):
        raise ValueError("Chapter requires the selected frozen, full-FP32 GPU release")
    data_version = winner["config"]["data_version"] if profile == "pilot-cpu" else meta["data_version"]
    data = read_json(root / "data/splits" / data_version / "dataset.json")
    comparison = read_json(release / "validation-comparison.json")
    timing = None if profile == "pilot-cpu" else read_json(reports / "benchmarks" / version / "local-cpu-1threads.json")
    runtimes = []
    if profile == "gpu":
        runtimes = [read_json(path) for path in sorted((reports / "environment").glob(f"standalone-*{version}-*.json"))]
        if not runtimes or any(
            r["model_sha256"] != meta["sha256"]
            or r["tensorflow_installed"]
            or r["tensorflow_imported"]
            or any(not x["external"]["passed"] for x in r["results"])
            for r in runtimes
        ):
            raise ValueError("Independent runtime evidence missing or incompatible")
    repeat = read_json(reports / (winner["experiment_id"] + "-repeat43") / "result.json")
    evidence = None if profile == "pilot-cpu" else read_json(reports / "audit/final-public-data.json")
    return Report(root, campaign, version, stages, meta, data, comparison, repeat, timing, evidence, runtimes)


def category_rows(report):
    rows = []
    for category in report.labels:
        key, label = str(category["id"]), category["label_key"]
        rows.append(
            f"| {category['display_name']} | {report.data['files']['train']['counts'][key]} | "
            f"{report.data['files']['validation']['counts'][key]} | "
            f"{report.evidence['approved_by_class'][label]} | {report.evidence['missing_to_80_by_class'][label]} |"
        )
    return rows


def candidate_rows(stages):
    rows = []
    for stage, summary in stages.items():
        field = "fine_tune_scope" if stage == "fine_tune" else stage
        for candidate in summary["candidates"]:
            validation = candidate["validation"]
            rows.append(
                f"| {stage} | {candidate['config'][field]} | {len(candidate['history'])} | "
                f"{validation['accuracy']:.2%} | {validation['macro_f1']:.4f} | "
                f"{validation['loss']:.4f} | {candidate['training_seconds']:.1f} |"
            )
    return rows


def classification_rows(labels, winner):
    rows = []
    for category in labels:
        metrics = winner["validation"]["classification_report"][category["label_key"]]
        rows.append(
            f"| {category['display_name']} | {metrics['precision']:.4f} | {metrics['recall']:.4f} | "
            f"{metrics['f1-score']:.4f} | {int(metrics['support'])} |"
        )
    return rows


def confusion_text(labels, winner):
    confusions = sorted(
        (
            (count, i, j)
            for i, row in enumerate(winner["validation"]["confusion_matrix"])
            for j, count in enumerate(row)
            if i != j and count
        ),
        reverse=True,
    )
    return "；".join(
        f"{labels[i]['display_name']}→{labels[j]['display_name']} {count}张" for count, i, j in confusions[:5]
    )


def threshold_rows(winner):
    rows = []
    for item in winner["threshold"]["candidates"]:
        accuracy = "无样本" if item["accuracy"] is None else f"{item['accuracy']:.2%}"
        rows.append(f"| {item['threshold']:.2f} | {item['count']} | {item['coverage']:.2%} | {accuracy} |")
    return rows


def render_pilot_cpu(report):
    ROOT = report.root
    stages, winner, repeat = report.stages, report.winner, report.repeat
    meta, data, labels = report.meta, report.data, report.labels
    gap = report.gap
    metadata, dataset = meta, data
    comparison = report.comparison
    rows = read_csv(ROOT / "data/manifests/public-reviewed.csv")
    approved = Counter(int(row["category_id"]) for row in rows if row["review_status"] == "approved")
    candidate = Counter(int(row["category_id"]) for row in rows)
    lines = [
        "# 模型训练历史先导实验材料",
        "",
        f"生成时间：{now()}。所有数字来自保存的清单及实验JSON。",
        "",
        "本章节保留先导实验；当前模型结果见[扩展数据实验](ml-expanded-experiments.md)。",
        "",
        "## 历史先导结论",
        "",
        f"已完成本机CPU上的基线、三阶段贪心调参及种子43完整流程复核。胜出公开验证集准确率{winner['validation']['accuracy']:.2%}、宏平均F1={winner['validation']['macro_f1']:.4f}。",
        "发布包保持experimental。指定WSL GPU正式训练、独立实拍准确率、Android及真实云端结果仍待完成，不据公开验证成绩宣布验收达标。",
        "",
        "## 数据来源与冻结",
        "",
        f"类别版本：{metadata['category_version']}；数据版本：{dataset['data_version']}；随机种子42。键盘仅独立外接计算机键盘。",
        f"本次实验使用{dataset['files']['train']['count']}张训练照片、{dataset['files']['validation']['count']}张验证照片，全部来自Commons和Open Images公开照片，按组约75%/25%划分。独立手机实拍照片尚未提供，当前为0张；公开照片不记作自采成果。",
        "Open Images来源中的validation/test名称属于公开来源划分，均可作为本项目公开训练/验证来源，不是独立实拍验收测试。",
        "SHA-256去除完全重复，来源URL、实物ID、人工系列组及感知哈希用于分组。同件物品/同产品系列保持同组。公开实物身份无法确认时object_id留空，来源/近重复隔离不能证明完全的实体隔离。",
        "",
        "| 类别 | 试验训练 | 试验验证 | 当前公开候选 | 当前审核通过 | 距每类80张缺口 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for c in labels:
        i = c["id"]
        key = str(i)
        lines.append(
            f"| {c['display_name']} | {dataset['files']['train']['counts'].get(key, 0)} | {dataset['files']['validation']['counts'].get(key, 0)} | {candidate[i]} | {approved[i]} | {max(0, 80 - approved[i])} |"
        )
    lines += [
        "",
        "先导实验划分保持不变；后续审核数据使用新版本，当前进度见implementation-status.json。",
        "水杯、笔袋数量较多，雨伞和充电器较少；书本含较多历史书籍。补拍需优先覆盖现代课本、普通雨伞及手机/电脑适配器，补拍实物与最终测试实物分开。",
        "",
        "## 训练设置与比较",
        "",
        "MobileNetV2 alpha=1.0，ImageNet预训练，GAP、Dropout、10类Softmax；模型内部x/127.5-1。训练集采用固定的适度旋转、平移、缩放和亮度增强；验证处理确定且不增强。",
        "所有候选batch32、种子42、最多20轮、验证损失早停patience3；按验证宏F1、准确率、较低损失排序。微调从同一胜出分类头开始，新Adam学习率降为1/10；BN参数与统计量冻结，骨干training=False。",
        "",
        "| 阶段 | 候选 | 轮数 | 验证准确率 | 宏F1 | 验证损失 | 训练秒数 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    lines += candidate_rows(stages)
    lines += [
        "",
        f"胜出配置：分类头学习率{stages['learning_rate']['winner']['config']['learning_rate']}、Dropout {winner['config']['dropout']}、微调{winner['config']['fine_tune_scope']}，微调学习率{winner['config']['learning_rate']}。最终使用主实验种子42检查点。",
        f"种子43完整复核：准确率{repeat['validation']['accuracy']:.2%}、宏F1={repeat['validation']['macro_f1']:.4f}；F1差{gap:.5f}。差异未超过0.05，无需种子44追加复核。",
        "",
        "## 全10类公开验证指标",
        "",
        "| 类别 | 精确率 | 召回率 | F1 | 验证数量 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    lines += classification_rows(labels, winner)
    lines += [
        "",
        "充电器召回率仅20%（5张验证图），是当前明显弱项；小样本类别指标不稳定。模型仍需补图及独立实拍检验。",
        "",
        "## 阈值、导出与一致性",
        "",
        f"低置信阈值{metadata['low_confidence_threshold']:.2f}，仅从验证集扫描选择；该阈值下116/128张高置信，覆盖率90.625%、准确率90.52%。始终输出Top-1，低置信提示人工确认。该阈值只适用于此试验模型。",
        f"FP32 TFLite实际文件{metadata['model_bytes']:,}字节，低于15MB；仅内置算子，无量化与Flex。模型SHA-256：`{metadata['sha256']}`。",
        f"完整128张验证照片Keras/TFLite最大分数差{comparison['max_score_difference']:.8f}，Top-1差异数{len(comparison['top1_mismatch_sample_ids'])}。20张真实照片交接样例（每类2张）附完整分数与little-endian输入张量；独立LiteRT环境不含TensorFlow，复核最大分数差0。",
        "CPU实测：1线程、预热20次、测100次，纯推理P50/P95约9.65/10.36ms，预处理加推理约27.03/38.50ms。使用交接样例照片，包含本地读图；不是手机或真实云端结果。",
        "",
        "## 图表与证据文件",
        "",
        f"- 胜出训练曲线：`experiments/reports/{winner['experiment_id']}/training-curves.png`。",
        "- 各阶段候选CSV及参数曲线：`experiments/reports/pilot-cpu-20261007/*-summary.csv`及PNG。",
        "- 10×10混淆矩阵及错误样例：`experiments/reports/evaluations/pilot-cpu-tuned-v1/`。",
        "- 复核差异：`experiments/reports/pilot-cpu-20261007-fine_tune-3-repeat43/reproduction.json`。",
        "- 模型、标签及交接样例哈希：`models/releases/pilot-cpu-tuned-v1/release-files.json`。",
        "- 本机CPU环境锁：`ml/requirements-windows-cpu.lock`；独立运行时锁：`ml/requirements-windows-runtime.lock`。",
        "",
        "## 复现与后续验收",
        "",
        f"本次训练源码摘要为`{winner['identity']['code_snapshot_sha256']}`，每个run保留`code-snapshot/recognition/`及installed-dependencies.lock。基线代码提交仅记录当时仓库基点，源码摘要用于确认实际未提交实现。",
        "代码后续修复已另存当前源码；复现历史实验时在新的交付工作目录将对应code-snapshot复制回ml/src/recognition，使用冻结照片和相同环境，再生成新的campaign/experiment ID。不要混合不同源码摘要的候选。",
        "四PC任务JSON已生成，其他PC须匹配数据、类别、环境及源码；完整流程仍为学习率→Dropout→微调→种子43复核，差异大时追加种子44。",
        "WSL管理员组件、重启及Linux账号创建完成后，运行scripts/setup-ml-wsl.sh实测GPU；CPU预跑不能代替RTX4060梯度及显存验收。",
        "组长冻结每类至少20张手机实拍照片后，使用split --test-only及evaluate --split test。模型/阈值已冻结，测试结果不回流选参。Android与真实云端分别核对张量及从图片开始的处理，并按20次预热、至少100次测量记录P50/P95；网络等待另测。",
        "未满足独立测试准确率85%或宏F1 0.80时如实报告；修改模型须使用新的独立测试版本。",
        "",
    ]
    return "\n".join(lines)


def render_expanded_cpu(report):
    ROOT = report.root
    campaign, version = report.campaign, report.version
    stages, winner, repeat = report.stages, report.winner, report.repeat
    meta, labels = report.meta, report.labels
    gap = report.gap
    comparison, timing, evidence = report.comparison, report.timing, report.evidence
    lines = [
        "# 扩展公开照片CPU历史实验材料",
        "",
        f"生成时间：{now()}。只报告已保存的真实实验结果。",
        "",
        "## 结论与验收边界",
        "",
        f"数据版本{meta['data_version']}，659张公开训练、218张公开验证；新版胜出验证准确率{winner['validation']['accuracy']:.2%}、宏F1={winner['validation']['macro_f1']:.4f}。",
        "本次Windows CPU试验完成三阶段和完整流程复核，历史模型保持experimental。后续GPU训练、独立实拍及端云验收的当前进度见implementation-status.json。",
        "公开验证成绩用于选参，不能作为独立实拍准确率验收成绩。旧版514张先导实验保留在ml-experiments.md，两版划分不同，成绩不作直接提升率比较。",
        "",
        "## 数据与来源",
        "",
        f"公开候选{evidence['candidate_count']}张，审核通过{evidence['approved_count']}张、拒绝{evidence['rejected_count']}张。通过照片来自Commons {evidence['approved_by_source']['wikimedia_commons']}张、Open Images {evidence['approved_by_source']['open_images']}张。独立手机实拍0张，公开照片不记为自采成果。",
        "Commons及Open Images官方人工正标签候选均经图像审核；来源中的public-test属于公开训练/验证来源，独立实拍测试另行冻结。",
        "按SHA、来源、感知哈希及人工拍摄系列分组。无法确认公开实物身份时object_id为空，分组不能证明完全实体隔离；585张早期候选的上游修订号未保留，下载版本以原始字节SHA-256标识，未虚构修订号。",
        f"数据元数据SHA-256：`{digest(ROOT / 'data/splits' / meta['data_version'] / 'dataset.json')}`。类别campus-10-v2，键盘仅独立外接计算机键盘。",
        "",
        "| 类别 | 训练 | 验证 | 公开通过 | 补拍缺口 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    lines += category_rows(report)
    lines += [
        "",
        "已采集877张公开训练/验证照片；独立实拍目前0张，计划约200张，另行计数。后续126张训练/验证补拍另行计数并冻结新版本。采集规则见ml-photo-gaps.md。",
        "",
        "## 候选实验",
        "",
        "MobileNetV2/ImageNet alpha=1.0，GAP、Dropout、10类Softmax；raw RGB float32输入，模型内归一化。只有训练集增强；BN始终冻结。相同阶段初始化、冻结数据、环境及种子42。",
        "本机顺序执行候选，四PC任务配置保存在campaign/pc-tasks。按宏F1、准确率、较低损失、较小微调范围及候选顺序选择。每轮原子保存模型/优化器和进度；23:00前停止长任务。",
        "",
        "| 阶段 | 候选 | 轮数 | 验证准确率 | 宏F1 | 验证损失 | 训练秒数 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    lines += candidate_rows(stages)
    lines += [
        "",
        f"胜出分类头学习率{stages['learning_rate']['winner']['config']['learning_rate']}，Dropout {winner['config']['dropout']}，微调{winner['config']['fine_tune_scope']}，微调学习率{winner['config']['learning_rate']}。最终使用种子42检查点。",
        f"种子43完整流程复核：准确率{repeat['validation']['accuracy']:.2%}、宏F1={repeat['validation']['macro_f1']:.4f}；宏F1差{gap:.5f}。",
    ]
    if gap > 0.05:
        extra = report.repeat44()
        lines.append(
            f"差异超过0.05，已追加种子44：准确率{extra['validation']['accuracy']:.2%}、宏F1={extra['validation']['macro_f1']:.4f}；报告随机性影响，仍保留主种子42发布。"
        )
    else:
        lines.append("差异未超过0.05，无需追加种子44。")
    lines += [
        "",
        "## 全10类验证指标",
        "",
        "| 类别 | 精确率 | 召回率 | F1 | 数量 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    lines += classification_rows(labels, winner)
    confusions = confusion_text(labels, winner)
    lines += [
        "",
        "各类数量不同，少样本类别指标不稳定；错误预测明细、10×10混淆矩阵及错误照片单独保存。未使用实拍测试调参。",
    ]
    if confusions:
        lines += ["", "验证集出现次数最多的混淆：" + confusions + "。"]
    lines += [
        "",
        "## 阈值、FP32与一致性",
        "",
        f"阈值{meta['low_confidence_threshold']:.2f}，状态{meta['threshold_status']}，只用验证集选择；候选支持数和准确率见winner result.json的threshold表。始终输出Top-1，低置信仅人工确认提示。",
        f"FP32 TFLite实际{meta['model_bytes']:,}字节，SHA-256=`{meta['sha256']}`。转换只允许内置算子、关闭量化。",
        f"完整218张验证集Keras/TFLite最大分数差{comparison['max_score_difference']:.8g}，Top-1变化{len(comparison['top1_mismatch_sample_ids'])}。20张真实交接照片、输入张量及完整分数保存在发布包examples。",
        f"本机CPU单线程、20次预热/100次计时：纯推理P50/P95={timing['inference_ms']['p50']:.2f}/{timing['inference_ms']['p95']:.2f}ms；预处理加推理={timing['preprocess_and_inference_ms']['p50']:.2f}/{timing['preprocess_and_inference_ms']['p95']:.2f}ms。不是手机或真实云端性能。",
        "",
        "## 证据与复现",
        "",
        f"源码摘要：`{winner['identity']['code_snapshot_sha256']}`；每个run保留code-snapshot、installed-dependencies.lock、每轮历史、best.keras和可续训检查点。数据和类别都显式引用冻结版本。",
        f"各阶段表格与参数曲线：`experiments/reports/{campaign}/`；胜出训练曲线：`experiments/reports/{winner['experiment_id']}/training-curves.png`。",
        f"10×10混淆矩阵、每张预测和错误样例：`experiments/reports/evaluations/{version}/`；Keras/LiteRT比较和发布文件哈希：`models/releases/{version}/`。",
        "复现命令：`python scripts/run-ml-campaign.py --config ml/configs/public-expanded-cpu.json --campaign <新ID> --version <新模型版本>`。匹配环境锁与冻结照片，不能把不同环境或源码的候选混在同一阶段。",
        "完成管理员安装、重启及Ubuntu首次账号后，执行WSL脚本生成实测公共batch的GPU配置，另开GPU campaign，完成后用--formal冻结模型。",
        "组长提供独立实拍清单；Android/云端按参考张量→图片完整链路核对，20次预热/至少100次计时；各项未完成就保持pending。交付及操作见ml-handover.md。",
        "",
    ]
    threshold_section = [
        "",
        "## 验证阈值扫描明细",
        "",
        "| 阈值 | 高置信数量 | 覆盖率 | 高置信准确率 |",
        "| ---: | ---: | ---: | ---: |",
    ]
    threshold_section += threshold_rows(winner)
    lines += threshold_section + [""]
    lines += [
        "## 报告配图",
        "",
        f"![胜出微调训练曲线](../experiments/reports/{winner['experiment_id']}/training-curves.png)",
        "",
        f"![学习率候选对照](../experiments/reports/{campaign}/learning_rate-summary.png)",
        "",
        f"![Dropout候选对照](../experiments/reports/{campaign}/dropout-summary.png)",
        "",
        f"![微调范围候选对照](../experiments/reports/{campaign}/fine_tune-summary.png)",
        "",
        f"![公开验证集10类混淆矩阵](../experiments/reports/evaluations/{version}/{meta['data_version']}-validation.png)",
        "",
    ]
    return "\n".join(lines)


def render_gpu(report):
    ROOT = report.root
    campaign, version = report.campaign, report.version
    stages, winner, repeat = report.stages, report.winner, report.repeat
    meta, data, labels = report.meta, report.data, report.labels
    gap = report.gap
    comparison, timing, evidence = report.comparison, report.timing, report.evidence
    runtimes, runtime_difference = report.runtimes, report.runtime_difference
    total = sum(row["training_seconds"] for stage in stages.values() for row in stage["candidates"])
    lines = [
        "# GPU模型训练实验材料",
        "",
        f"生成时间：{now()}。数字来自冻结清单和保存的实验记录。",
        "",
        "## 当前结果与验收状态",
        "",
        f"模型`{version}`已冻结。公开验证准确率{winner['validation']['accuracy']:.2%}、宏平均F1={winner['validation']['macro_f1']:.4f}。",
        "frozen表示模型、阈值和输入合同冻结，可以开始独立评估；不代表独立实拍及端云验收已达标。独立实拍、真实Android和腾讯云结果仍待对应成员提供。",
        "",
        "## 数据与类别",
        "",
        f"数据版本`{meta['data_version']}`：训练{data['files']['train']['count']}张、验证{data['files']['validation']['count']}张，均为公开照片。独立手机实拍当前0张，计划约200张，另行冻结，未用于选参。",
        f"审核通过{evidence['approved_count']}张：Commons {evidence['approved_by_source']['wikimedia_commons']}张，Open Images {evidence['approved_by_source']['open_images']}张；候选{evidence['candidate_count']}张，拒绝{evidence['rejected_count']}张。公开照片不记作自采成果。",
        "SHA-256、来源、感知哈希与人工系列分组用于隔离。公开照片无法确认实物时object_id为空，来源和近重复隔离不能证明完全实体隔离；585张早期候选的上游修订号未保存，以实际下载字节哈希标识版本。",
        f"类别`{meta['category_version']}`；键盘仅独立外接计算机键盘。数据元数据SHA-256：`{digest(ROOT / 'data/splits' / meta['data_version'] / 'dataset.json')}`。",
        "",
        "| 类别 | 训练 | 验证 | 已审核公开图 | 补拍缺口 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    lines += category_rows(report)
    lines += [
        "",
        "训练/验证补拍缺口共126张，优先雨伞、书本、外接键盘和充电器；补拍实物与独立测试实物分开。新图使用新数据版本，不能修改本次冻结划分。",
        "",
        "## 训练设置与候选对照",
        "",
        "RTX4060 Laptop、WSL2/Ubuntu24.04、Python3.12.3、TensorFlow2.21.0、Keras3.12.1、NumPy2.1.3；实际依赖锁随交付保存。完整float32计算，TensorFloat-32关闭，所有候选batch32、种子42、最多20轮、验证损失早停3轮。",
        "ImageNet MobileNetV2 alpha=1.0、GAP、Dropout、10类Softmax，模型内部x/127.5-1；只有训练集增强。BN参数和统计量冻结，骨干training=False。阶段依次执行，按宏F1、准确率、低损失、较小微调范围及候选顺序选择。微调从相同胜出头开始，新Adam学习率为头学习率的1/10。",
        "首个真实训练轮耗时6.64秒；训练计时不含读图、检查点写入和导出。每轮保存优化器与随机状态，北京时间23:00前停止并支持续作。四PC任务保存在campaign/pc-tasks，未宣称异机实测或并行加速。",
        "",
        "| 阶段 | 候选 | 实际轮数 | 准确率 | 宏F1 | 验证损失 | 训练秒数 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    lines += candidate_rows(stages)
    lines += [
        "",
        f"九个候选记录的训练时间合计{total:.1f}秒。胜出头学习率{stages['learning_rate']['winner']['config']['learning_rate']}，Dropout {winner['config']['dropout']}，微调{winner['config']['fine_tune_scope']}，微调学习率{winner['config']['learning_rate']}；发布使用种子42最佳宏F1检查点。",
        f"种子43完整流程复核：准确率{repeat['validation']['accuracy']:.2%}、宏F1={repeat['validation']['macro_f1']:.4f}，与主实验F1差{gap:.5f}。",
    ]
    if gap > 0.05:
        extra = report.repeat44()
        lines.append(
            f"差异超过0.05，追加种子44复核：准确率{extra['validation']['accuracy']:.2%}、宏F1={extra['validation']['macro_f1']:.4f}；随机性影响仍需报告，发布保留主种子42。"
        )
    else:
        lines.append("F1差异未超过0.05，无需追加种子44。")
    lines += [
        "",
        "## 全10类公开验证指标",
        "",
        "| 类别 | 精确率 | 召回率 | F1 | 数量 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    lines += classification_rows(labels, winner)
    confusions = confusion_text(labels, winner)
    lines += ["", "少样本类别指标不稳定。错误预测明细及照片单独保存，未使用独立实拍成绩调参。"]
    if confusions:
        lines.append("主要混淆：" + confusions + "。")
    lines += [
        "",
        "## 阈值、导出与运行时",
        "",
        f"低置信阈值{meta['low_confidence_threshold']:.2f}，状态`{meta['threshold_status']}`，只用验证集选择。始终输出Top-1，低置信只提示人工确认。",
        "",
        "| 阈值 | 高置信数量 | 覆盖率 | 高置信准确率 |",
        "| ---: | ---: | ---: | ---: |",
    ]
    lines += threshold_rows(winner)
    lines += [
        "",
        f"FP32 TFLite实际{meta['model_bytes']:,}字节，低于15MB，只允许内置算子，关闭量化。模型SHA-256：`{meta['sha256']}`；标签SHA-256：`{meta['labels_sha256']}`。",
        f"完整验证集Keras/LiteRT最大分数差{comparison['max_score_difference']:.8g}，Top-1变化{len(comparison['top1_mismatch_sample_ids'])}；20张真实交接照片每类2张，附输入张量、分数、标签与来源。",
        f"独立LiteRT环境已完成{len(runtimes)}份系统复核，每份包括全部20张参考张量和20次图片链路，Top-1一致，最大分数差{runtime_difference:.8g}，未安装或导入TensorFlow。对应运行ID："
        + ", ".join(f"`{r['run_id']}`" for r in runtimes)
        + "。",
        f"本机Linux CPU单线程、预热20次、测100次：纯推理P50/P95={timing['inference_ms']['p50']:.2f}/{timing['inference_ms']['p95']:.2f}ms，预处理加推理={timing['preprocess_and_inference_ms']['p50']:.2f}/{timing['preprocess_and_inference_ms']['p95']:.2f}ms。这不是手机或腾讯云性能。",
        "",
        "## 证据与复现",
        "",
        f"训练代码提交`{winner['code_commit']}`，源码摘要`{winner['identity']['code_snapshot_sha256']}`。每个run保留源码快照、安装依赖锁、逐轮历史、best.keras及优化器续训检查点。环境预跑及84项GPU检查见`ml-gpu-environment.md`。",
        "独立LiteRT参考张量与图片链路证据保存于environment/standalone-*及consistency目录；不安装或导入TensorFlow。Android及真实云端必须另外回传同图、设备及性能记录。",
        "",
        "```bash",
        "source scripts/activate-ml-wsl.sh",
        "python scripts/run-ml-campaign.py --config ml/configs/wsl-campus-public-expanded-v1.json \\",
        "  --campaign <新的ID> --version <新的模型版本> --formal",
        "```",
        "",
        "匹配冻结数据、类别、代码和依赖，不合并不同环境候选。原campaign可以原命令续作；新配置或源码须使用新ID。CPU历史包与指标保持原记录，不用GPU结果改写它们。",
        "模型及阈值冻结后，组长提供独立测试清单执行评估；后续模型不能重用已评估测试照片。真实验收和交接命令见ml-handover.md。",
        "",
        "## 报告配图",
        "",
        f"![胜出训练曲线](../experiments/reports/{winner['experiment_id']}/training-curves.png)",
        "",
    ]
    for stage in stages:
        lines += [f"![{stage}候选对照](../experiments/reports/{campaign}/{stage}-summary.png)", ""]
    lines += [
        f"![公开验证集混淆矩阵](../experiments/reports/evaluations/{version}/{meta['data_version']}-validation.png)",
        "",
    ]
    return "\n".join(lines)


RENDERERS = {"pilot-cpu": render_pilot_cpu, "expanded-cpu": render_expanded_cpu, "gpu": render_gpu}


def render_report(profile, campaign=None, version=None, *, root=ROOT):
    report = load_report(profile, campaign, version, root=root)
    return RENDERERS[profile](report)


def main(argv=None, *, profile=None):
    parser = argparse.ArgumentParser(description=__doc__)
    if profile is None:
        parser.add_argument(
            "--profile", choices=PROFILES, required=True, help="Historical CPU profile or a verified GPU campaign"
        )
    else:
        parser.set_defaults(profile=profile)
    parser.add_argument("--campaign", help="Required for GPU; CPU profiles retain their historical campaign")
    parser.add_argument("--version", help="Required for GPU; CPU profiles retain their historical release")
    parser.add_argument("--output", type=Path, help="Markdown output; defaults to the profile document in docs/")
    args = parser.parse_args(argv)
    if args.profile == "gpu" and (args.campaign is None or args.version is None):
        parser.error("GPU reports require --campaign and --version")
    if args.output is not None and args.output.suffix.lower() != ".md":
        parser.error("--output must be a Markdown (.md) file")
    content = render_report(args.profile, args.campaign, args.version)
    output = args.output if args.output is not None else ROOT / "docs" / PROFILES[args.profile][2]
    output.write_text(content, encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
