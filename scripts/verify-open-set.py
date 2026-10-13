"""Read-only independent LiteRT comparison. Never selects thresholds on holdout."""
import argparse
from collections import Counter
import csv
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import time
import numpy as np
from recognition.inference import LiteRunner
from recognition.preprocessing import preprocess
from recognition.open_set import summarize, accepted
from recognition.scope import decisions


def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf8', newline='\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('candidate', 'parent', 'data-root', 'aux-data', 'diagnostic-image', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Preserve previous verification; choose a new output directory')
    args.output.mkdir(parents=True)
    candidate, parent = LiteRunner(args.candidate, threads=1), LiteRunner(args.parent, threads=1)
    policy = candidate.scope_policy
    threshold = policy['knownness_threshold']
    manifest = args.data_root / 'data/splits' / candidate.metadata['data_version'] / 'validation.csv'
    if sha(manifest) != policy['calibration']['known_validation_sha256']:
        raise ValueError('Known validation manifest changed')
    if sha(args.aux_data / 'samples.csv') != policy['calibration']['auxiliary_manifest_sha256']:
        raise ValueError('Unknown manifest changed')
    protected = {name: sha(args.candidate / name) for name in ('model.tflite', 'metadata.json', 'scope-policy.json')}
    known = read_csv(manifest)
    unknown = [row for row in read_csv(args.aux_data / 'samples.csv') if row['split'] == 'holdout']
    arrays = {}
    raw = []
    for split, rows, root in [('known', known, args.data_root), ('unknown', unknown, args.aux_data)]:
        baseline_scores, scores, knownness = [], [], []
        for i, row in enumerate(rows):
            path = (root / row['image_path']).resolve()
            if not path.is_relative_to(root.resolve()) or sha(path) != row['image_sha256']:
                raise ValueError('Sample path/hash changed')
            tensor = preprocess(path)
            base, result = parent.predict_outputs(tensor), candidate.predict_outputs(tensor)
            baseline_scores.append(base['scores']); scores.append(result['scores']); knownness.append(result['knownness'])
            raw.append({'sample_id': row['sample_id'], 'image_sha256': row['image_sha256'], 'split': split,
                        'semantic_class': row.get('semantic_class'), 'scores': result['scores'].tolist(),
                        'knownness': result['knownness'], 'parent_scores': base['scores'].tolist()})
            if i % 100 == 0:
                print(split, i + 1, '/', len(rows), flush=True)
        arrays[split] = (np.array(baseline_scores), np.array(scores), np.array(knownness))
    bk, sk, kk = arrays['known']; bu, su, ku = arrays['unknown']
    labels = np.array([int(row['category_id']) for row in known])
    max_delta = max(float(np.max(np.abs(bk - sk))), float(np.max(np.abs(bu - su))))
    changes = int((bk.argmax(1) != sk.argmax(1)).sum() + (bu.argmax(1) != su.argmax(1)).sum())
    if max_delta > .001 or changes:
        raise ValueError('Original classification scores changed unexpectedly')
    metrics = summarize(sk, labels, kk, su, ku, threshold)
    baseline = {'known_accepted': int(decisions(bk, .55, .20).sum()),
                'unknown_rejected': int((~decisions(bu, .55, .20)).sum()),
                'unknown_count': len(unknown)}
    diagnostic = candidate.predict_outputs(preprocess(args.diagnostic_image))
    gecko = {'image_sha256': sha(args.diagnostic_image), 'scores': diagnostic['scores'].tolist(),
             'knownness': diagnostic['knownness'],
             'accepted': bool(accepted(diagnostic['scores'][None], [diagnostic['knownness']], threshold)[0]),
             'used_for_training_or_selection': False}
    # Repeated timings use the same actual known image, including file decode + preprocessing.
    bench_image = args.data_root / known[0]['image_path']
    inference_ms, full_ms = [], []
    for i in range(120):
        start = time.perf_counter(); tensor = preprocess(bench_image); ready = time.perf_counter()
        candidate.predict_outputs(tensor); end = time.perf_counter()
        if i >= 20:
            inference_ms.append((end-ready)*1000); full_ms.append((end-start)*1000)
    for name, expected in protected.items():
        if sha(args.candidate / name) != expected:
            raise ValueError('Frozen candidate changed during verification')
    per_unknown = {}
    flags = accepted(su, ku, threshold)
    for cls in sorted({row['semantic_class'] for row in unknown}):
        mask = np.array([row['semantic_class'] == cls for row in unknown])
        per_unknown[cls] = {'count': int(mask.sum()), 'rejected': int((~flags[mask]).sum())}
    confusion = np.zeros((10, 10), dtype=int)
    np.add.at(confusion, (labels, sk.argmax(1)), 1)
    class_report = {}
    f1s = []
    for i, label in enumerate(candidate.labels):
        tp = int(confusion[i,i]); precision = tp/max(1, int(confusion[:,i].sum())); recall = tp/max(1, int(confusion[i].sum()))
        f1 = 2*precision*recall/max(1e-20, precision+recall); f1s.append(f1)
        class_report[label] = {'precision': precision, 'recall': recall, 'f1': f1, 'support': int(confusion[i].sum())}
    report = {'model_version': candidate.metadata['model_version'], 'model_sha256': protected['model.tflite'],
              'policy_sha256': protected['scope-policy.json'], 'runtime': {'python': platform.python_version(),
              'platform': platform.platform(), 'ai_edge_litert': importlib.metadata.version('ai-edge-litert'), 'threads': 1},
              'metrics': metrics, 'baseline_same_samples': baseline, 'per_unknown_class': per_unknown,
              'raw_known_macro_f1': float(np.mean(f1s)), 'classification_report': class_report, 'confusion_matrix': confusion.tolist(),
              'unchanged_classifier': {'max_score_error': max_delta, 'top1_changes': changes}, 'gecko_development_diagnostic': gecko,
              'benchmark': {'warmup': 20, 'measurements': 100, 'inference_p50_ms': float(np.percentile(inference_ms,50)),
              'inference_p95_ms': float(np.percentile(inference_ms,95)), 'preprocess_and_inference_p50_ms': float(np.percentile(full_ms,50)),
              'preprocess_and_inference_p95_ms': float(np.percentile(full_ms,95)), 'device_scope': 'Windows development CPU, not phone'},
              'limitations': ['Known validation participated in policy selection.',
                  'Unknown holdout comes from one public source, not an independent phone acceptance set.',
                  'Gecko is a development diagnostic, not a holdout estimate.']}
    write(args.output / 'report.json', report)
    write(args.output / 'predictions.json', raw)
    np.savez_compressed(args.output / 'outputs.npz', known_scores=sk, knownness=kk, unknown_scores=su, unknownness=ku)
    print(json.dumps({key: report[key] for key in ('metrics','baseline_same_samples','unchanged_classifier','benchmark','gecko_development_diagnostic')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
