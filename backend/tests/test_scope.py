import copy
import pytest
from app.inference.scope import basic_policy, decide, policy_for_contract


def contract():
    policy = basic_policy()
    return {key: policy[key] for key in ['model_version', 'model_sha256', 'labels_sha256', 'category_version']}


def result(scores=None):
    return dict(contract(), scores=scores or [.91] + [.01]*9)


def test_cloud_uncertain_is_a_state_and_keeps_the_ten_class_candidate():
    prediction = result([.56, .44] + [0]*8)
    original = copy.deepcopy(prediction)
    decision = decide(prediction, contract())
    assert decision['status'] == 'uncertain'
    assert decision['needs_confirmation']
    assert decision['reason_code'] == 'AMBIGUOUS_CLASSES'
    assert prediction == original


def test_basic_policy_cannot_identify_high_confidence_unknowns():
    assert decide(result([.9999, .0001] + [0]*8), contract())['status'] == 'accepted'


def test_mismatched_model_does_not_borrow_v2_rules():
    other = dict(contract(), model_version='campus-gpu-v1', model_sha256='a'*64)
    decision = decide(dict(result(), **other), other)
    assert decision['status'] == 'unavailable' and decision['needs_confirmation']


def test_learned_knownness_can_reject_even_when_classification_is_certain():
    identity = dict(contract(), model_version='candidate-ood-v1', model_sha256='b'*64)
    policy = dict(basic_policy(), **identity, rule='learned_knownness_v1', policy_version='scope-knownness-v1',
                  policy_sha256='c'*64, knownness_threshold=.5)
    identity['scope_policy'] = policy
    prediction = dict(result([.9999, .0001] + [0]*8), model_version=identity['model_version'],
                      model_sha256=identity['model_sha256'], knownness=.1)
    decision = decide(prediction, identity)
    assert decision['status'] == 'uncertain' and decision['reason_code'] == 'SCOPE_MISMATCH'
    prediction['knownness'] = .9
    assert decide(prediction, identity)['status'] == 'accepted'
    del prediction['knownness']
    with pytest.raises(ValueError):
        decide(prediction, identity)


@pytest.mark.parametrize('scores', [[float('nan')]+[0]*9, [.2]*10, [1, 0]])
def test_invalid_scores_are_rejected(scores):
    with pytest.raises(ValueError):
        decide(result(scores), contract())


def test_invalid_policy_never_enables_automatic_acceptance():
    identity = contract()
    identity['scope_policy'] = dict(basic_policy(), knownness_threshold=float('nan'), rule='learned_knownness_v1')
    assert policy_for_contract(identity) is None
