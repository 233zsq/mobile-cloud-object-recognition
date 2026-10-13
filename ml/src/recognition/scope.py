"""Experimental score gates, developed on validation only; never final test selection."""
from pathlib import Path
import numpy as np
from .common import ROOT, digest, image_path, read_json, write_json, now
from .data import load_split
from .inference import LiteRunner


def decisions(scores, confidence, margin):
    scores = np.asarray(scores, dtype=np.float32)
    if scores.ndim != 2 or scores.shape[1] != 10 or len(scores) == 0:
        raise ValueError('Expected nonempty N x 10 scores')
    if not np.isfinite(scores).all() or (scores < 0).any() or (scores > 1).any() or not np.allclose(scores.sum(axis=1), 1, atol=1e-4, rtol=0):
        raise ValueError('Invalid softmax scores')
    if not 0 <= confidence <= 1 or not 0 <= margin <= 1:
        raise ValueError('Invalid scope thresholds')
    ordered = np.sort(scores, axis=1)
    return (ordered[:, -1] >= np.float32(confidence)) & (ordered[:, -1] - ordered[:, -2] >= np.float32(margin))


def gate_metrics(scores, labels, confidence, margin):
    accepted = decisions(scores, confidence, margin)
    labels = np.asarray(labels)
    if labels.shape != (len(scores),) or not np.isin(labels, np.arange(10)).all():
        raise ValueError('Expected known-class labels 0..9')
    correct = np.asarray(scores).argmax(axis=1) == labels
    total, count = len(labels), int(accepted.sum())
    return {'total': total, 'accepted': count, 'needs_confirmation': total-count,
            'known_coverage': count/total, 'known_false_rejection_rate': 1-count/total,
            'raw_accuracy': float(correct.mean()),
            'accepted_accuracy': float(correct[accepted].mean()) if count else None,
            'correct_and_accepted_over_all_known': float((correct & accepted).mean()),
            'per_class': {str(c): {'total': int((labels == c).sum()),
                                 'accepted': int((accepted & (labels == c)).sum())} for c in range(10)}}


def probe(release, data_version, output):
    output = Path(output)
    if output.exists():
        raise ValueError('Output exists; use a new policy probe version')
    runner = LiteRunner(release)
    rows, dataset = load_split(data_version, 'validation')
    if dataset['category_version'] != runner.metadata['category_version']:
        raise ValueError('Category versions differ')
    output.mkdir(parents=True)
    scores = []
    for i, row in enumerate(rows):
        scores.append(runner.predict_image(image_path(row['image_path']))['scores'])
        if (i+1) % 100 == 0:
            print(f'Scope validation {i+1}/{len(rows)}', flush=True)
    scores = np.asarray(scores, dtype=np.float32)
    labels = np.asarray([int(row['category_id']) for row in rows])
    presets = [(0.55, 0.20), (0.50, 0.15), (0.50, 0.10), (0.50, 0.0)]
    results = [{'confidence_threshold': c, 'margin_threshold': m, **gate_metrics(scores, labels, c, m)} for c, m in presets]
    # Predeclared bounded presets; no optimisation on unknown or final-test data.
    selected = next((r for r in results if r['known_coverage'] >= .90), results[-1])
    policy = {'policy_version': 'scope-basic-v1', 'status': 'experimental', 'rule': 'msp_margin_v1',
              'model_version': runner.metadata['model_version'], 'model_sha256': runner.metadata['sha256'],
              'labels_sha256': runner.metadata['labels_sha256'], 'category_version': dataset['category_version'],
              'preprocessing_version': runner.metadata['input']['version'],
              'confidence_threshold': selected['confidence_threshold'], 'margin_threshold': selected['margin_threshold'],
              'calibration': {'data_version': data_version, 'manifest_sha256': dataset['files']['validation']['sha256'],
                              'known_samples': len(rows), 'known_coverage': selected['known_coverage'],
                              'unknown_samples': 0, 'unknown_rejection_rate': None, 'status': 'known_validation_only'}}
    write_json(output/'scope-policy.json', policy)
    policy_hash = digest(output/'scope-policy.json')
    (output/'scope-policy.sha256').write_text(policy_hash+'\n', encoding='ascii')
    write_json(output/'validation-scores.json', {'model_sha256': policy['model_sha256'],
        'data_manifest_sha256': dataset['files']['validation']['sha256'],
        'samples': [{'sample_id': row['sample_id'], 'image_sha256': row['image_sha256'], 'category_id': int(row['category_id']),
                     'scores': score.tolist()} for row, score in zip(rows, scores)]})
    report = {'created_at': now(), 'policy_sha256': policy_hash, 'status': 'experimental',
              'selection_split': 'validation', 'final_test_images_read': False,
              'model_sha256': policy['model_sha256'], 'data_version': data_version,
              'presets': results, 'selected': selected,
              'unknown_rejection_rate': None,
              'limitations': ['Known validation selection is not independent field acceptance.',
                              'No reviewed out-of-scope evaluation set; unknown detection has not been established.',
                              'This policy changes UI confirmation, not the ten-class model or raw accuracy.']}
    write_json(output/'report.json', report)
    return report
