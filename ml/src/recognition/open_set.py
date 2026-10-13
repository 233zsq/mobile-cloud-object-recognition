"""Learned scope gate calibration. Unknown holdout never participates in selection."""
import numpy as np
from .scope import decisions


def accepted(scores, knownness, threshold):
    knownness = np.asarray(knownness, dtype=np.float32).reshape(-1)
    basic = decisions(scores, .55, .20)
    if len(knownness) != len(basic) or not np.isfinite(knownness).all() or (knownness < 0).any() or (knownness > 1).any():
        raise ValueError('Invalid knownness output')
    if not np.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError('Invalid knownness threshold')
    return basic & (knownness >= np.float32(threshold))


def summarize(known_scores, known_labels, knownness, unknown_scores, unknownness, threshold):
    known = accepted(known_scores, knownness, threshold)
    unknown = accepted(unknown_scores, unknownness, threshold)
    labels = np.asarray(known_labels)
    if labels.shape != (len(known),) or not np.isin(labels, np.arange(10)).all():
        raise ValueError('Expected known-class labels 0..9')
    correct = np.asarray(known_scores).argmax(axis=1) == labels
    return {'known_count': len(known), 'known_accepted': int(known.sum()), 'known_coverage': float(known.mean()),
            'known_false_rejection_rate': float((~known).mean()), 'raw_known_accuracy': float(correct.mean()),
            'accepted_known_accuracy': float(correct[known].mean()) if known.any() else None,
            'correct_and_accepted_over_all_known': float((known & correct).mean()),
            'unknown_count': len(unknown), 'unknown_rejected': int((~unknown).sum()),
            'unknown_rejection_rate': float((~unknown).mean()), 'unknown_false_acceptance_rate': float(unknown.mean()),
            'per_known_class': {str(c): {'total': int((labels == c).sum()),
                'accepted': int((known & (labels == c)).sum()),
                'coverage': float(known[labels == c].mean()) if (labels == c).any() else None} for c in range(10)}}


def calibrate(known_scores, labels, knownness, unknown_scores, unknownness):
    knownness = np.asarray(knownness, dtype=np.float32).reshape(-1)
    thresholds = np.unique(np.r_[0., np.linspace(.05, .95, 19), np.quantile(knownness, np.arange(.01, .151, .01))])
    table = []
    for threshold in thresholds:
        metrics = summarize(known_scores, labels, knownness, unknown_scores, unknownness, float(threshold))
        table.append({'threshold': float(np.float32(threshold)), **metrics})
    eligible = [row for row in table if row['known_coverage'] >= .90
                and all(item['coverage'] is not None and item['coverage'] >= .80 for item in row['per_known_class'].values())]
    if not eligible:
        raise ValueError('No candidate preserves declared known-class coverage')
    winner = max(eligible, key=lambda row: (row['unknown_rejection_rate'], row['known_coverage'], -row['threshold']))
    return {'selected': winner, 'candidates': table, 'selection_source': 'known validation and unknown calibration only'}
