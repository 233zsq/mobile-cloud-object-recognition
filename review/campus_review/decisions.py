"""Quick review choices, stored as ordinary status/reason for batch compatibility."""
from werkzeug.exceptions import BadRequest

REJECTIONS = {'occluded': '被遮挡', 'wrong_item': '此物品不是对应物品'}
CHOICES = [('approved', '通过'), *REJECTIONS.items(), ('other', '其他'), ('pending', '暂不判断')]


def initial_choice(sample):
    if sample['status'] != 'rejected':
        return 'approved', sample['reason']
    for code, label in REJECTIONS.items():
        if sample['reason'] == label or sample['reason'].startswith(label + '：'):
            return code, sample['reason'][len(label):].removeprefix('：')
    return 'other', sample['reason']


def resolve_choice(code, status, note):
    # Pages opened before this update still submit the original status/reason fields.
    if code is None:
        return status, note
    if code not in dict(CHOICES):
        raise BadRequest('未知审核结果，请刷新后重试')
    if code == 'other' and not note:
        raise BadRequest('选择其他时请填写拒绝原因')
    if code in REJECTIONS:
        note = REJECTIONS[code] + ('：' + note if note else '')
    if len(note) > 160:
        raise BadRequest('审核说明含快捷原因合计不能超过160个字符')
    return ('approved' if code == 'approved' else 'pending' if code == 'pending' else 'rejected'), note
