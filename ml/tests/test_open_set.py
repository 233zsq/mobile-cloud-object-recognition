import numpy as np
import pytest
from recognition.open_set import accepted, calibrate, summarize


def test_auxiliary_scope_head_can_reject_high_confidence_classification():
    scores = [[.9999, .0001] + [0]*8, [.9, .1] + [0]*8]
    assert accepted(scores, [.1, .9], .5).tolist() == [False, True]


def test_calibration_keeps_normal_objects_while_selecting_on_development_only():
    known = np.eye(10, dtype=np.float32)*.9 + (1-np.eye(10, dtype=np.float32))*(.1/9)
    unknown = np.tile([.9999, .0001] + [0]*8, (20, 1))
    result = calibrate(known, np.arange(10), np.ones(10)*.9, unknown, np.ones(20)*.1)
    assert result['selected']['known_coverage'] == 1
    assert result['selected']['unknown_rejection_rate'] == 1
    assert result['selection_source'].endswith('calibration only')


@pytest.mark.parametrize('knownness', [[float('nan')], [1.1], [-.1], [0, 1]])
def test_invalid_auxiliary_output_is_rejected(knownness):
    with pytest.raises(ValueError):
        accepted([[.9, .1] + [0]*8], knownness, .5)


def test_report_does_not_hide_rejected_normal_samples_from_the_denominator():
    scores = [[.9, .1] + [0]*8, [.9, .1] + [0]*8]
    report = summarize(scores, [0, 1], [.9, .1], scores[:1], [.1], .5)
    assert report['known_coverage'] == .5
    assert report['accepted_known_accuracy'] == 1
    assert report['correct_and_accepted_over_all_known'] == .5
