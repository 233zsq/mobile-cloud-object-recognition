"""Server-authoritative scope decisions; original ten-class scores remain unchanged."""
import hashlib
import json
from pathlib import Path
import math
import struct
import re

POLICIES = Path(__file__).resolve().parents[2] / 'policies'
BASIC_SHA256 = '3011b2f0b71a0592d17e598693af6f57b8155a05350afc43d521dc6df98bd842'


def basic_policy():
    try:
        content = (POLICIES / 'scope-basic-v1.json').read_bytes()
        if hashlib.sha256(content).hexdigest() != BASIC_SHA256:
            return None
        return dict(json.loads(content), policy_sha256=BASIC_SHA256)
    except (OSError, ValueError, TypeError):
        return None


def policy_for_contract(contract):
    policy = contract.get('scope_policy') if 'scope_policy' in contract else basic_policy()
    if not isinstance(policy, dict):
        return None
    for policy_key, contract_key in [('model_version', 'model_version'), ('model_sha256', 'model_sha256'),
                                     ('labels_sha256', 'labels_sha256'), ('category_version', 'category_version')]:
        if policy.get(policy_key) != contract.get(contract_key):
            return None
    if (policy.get('preprocessing_version') != 'rgb-letterbox-v1' or policy.get('status') not in ('experimental', 'frozen')
            or (policy.get('rule'), policy.get('policy_version')) not in
               (('msp_margin_v1', 'scope-basic-v1'), ('learned_knownness_v1', 'scope-knownness-v1'))):
        return None
    thresholds = ['confidence_threshold', 'margin_threshold']
    if policy['rule'] == 'learned_knownness_v1':
        thresholds.append('knownness_threshold')
    if any(type(policy.get(key)) not in (int, float) or not math.isfinite(policy[key]) or not 0 <= policy[key] <= 1 for key in thresholds):
        return None
    if (not isinstance(policy.get('policy_sha256'), str) or not re.fullmatch('[a-f0-9]{64}', policy['policy_sha256'])
            or not isinstance(policy.get('policy_version'), str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9._-]{0,63}', policy['policy_version'])):
        return None
    return policy


def f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def decide(result, contract):
    scores = result.get('scores')
    if (not isinstance(scores, list) or len(scores) != 10
            or any(type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1 for value in scores)
            or abs(sum(scores)-1) > .0001
            or result.get('model_version') != contract.get('model_version')
            or result.get('model_sha256') != contract.get('model_sha256')):
        raise ValueError('Invalid inference identity or scores')
    policy = policy_for_contract(contract)
    if policy is None:
        return {'status': 'unavailable', 'needs_confirmation': True, 'policy_version': None,
                'policy_sha256': None, 'reason_code': 'POLICY_UNAVAILABLE',
                'message': '当前模型没有匹配的范围判断规则，请人工确认类别。'}
    ordered = sorted(map(f32, scores), reverse=True)
    margin = f32(ordered[0] - ordered[1])
    reason = None
    knownness = None
    if ordered[0] < f32(policy['confidence_threshold']):
        reason = ('LOW_CONFIDENCE', '分类分数较低，请调整画面或人工确认。')
    elif margin < f32(policy['margin_threshold']):
        reason = ('AMBIGUOUS_CLASSES', '前两类分数接近，请调整画面或人工确认。')
    if policy['rule'] == 'learned_knownness_v1':
        knownness = result.get('knownness')
        if type(knownness) not in (int, float) or not math.isfinite(knownness) or not 0 <= knownness <= 1:
            raise ValueError('Missing or invalid learned knownness')
        if f32(knownness) < f32(policy['knownness_threshold']):
            reason = ('SCOPE_MISMATCH', '暂不确定，图片可能不在当前10类范围内，请人工确认。')
    return {'status': 'uncertain' if reason else 'accepted', 'needs_confirmation': bool(reason),
            'policy_version': policy['policy_version'], 'policy_sha256': policy['policy_sha256'],
            'rule': policy['rule'], 'margin': margin, 'knownness': knownness,
            'knownness_threshold': policy.get('knownness_threshold'),
            'reason_code': reason[0] if reason else 'RULES_PASSED',
            'message': reason[1] if reason else '范围判断规则通过，仍请以实际物品为准。'}


def response_contract(result, contracts):
    match = next((contract for contract in contracts if contract['model_version'] == result['model_version']), None)
    if match:
        return match
    # A legacy single-model installation has no registry. Only the exact pinned
    # v2 may inherit the bundled v2 label/category identity; all others fail closed.
    policy = basic_policy()
    if policy and (result['model_version'], result['model_sha256']) == (policy['model_version'], policy['model_sha256']):
        return {key: policy[key] for key in ['model_version', 'model_sha256', 'labels_sha256', 'category_version']}
    return {'model_version': result['model_version'], 'model_sha256': result['model_sha256']}
