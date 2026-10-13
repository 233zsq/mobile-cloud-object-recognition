import numpy as np
import pytest
from recognition.scope import decisions, gate_metrics


def test_close_top_two_scores_need_confirmation_even_above_confidence_gate():
    scores = [[.56, .44] + [0]*8, [.6, .1] + [.0375]*8]
    assert decisions(scores, .55, .2).tolist() == [False, True]


def test_reports_all_known_denominator_instead_of_only_accepted_accuracy():
    scores = [[.9, .1] + [0]*8, [.56, .44] + [0]*8]
    report = gate_metrics(scores, [0, 1], .55, .2)
    assert report['accepted_accuracy'] == 1
    assert report['known_coverage'] == .5
    assert report['correct_and_accepted_over_all_known'] == .5
    assert report['raw_accuracy'] == .5


@pytest.mark.parametrize('scores', [[], [[float('nan')]+[0]*9], [[.5]*10], [[1, 0]]])
def test_invalid_scores_cannot_be_accepted(scores):
    with pytest.raises(ValueError):
        decisions(scores, .55, .2)
