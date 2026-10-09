'use strict';
const reviewForm = document.querySelector('#review-form');
if (reviewForm && reviewForm.elements.lease.value) {
  const leaseMessage = document.querySelector('#lease-message');
  const reason = reviewForm.elements.reason;
  const notePanel = document.querySelector('#review-note');
  const updateDecision = () => {
    const choice = reviewForm.elements.decision.value;
    reason.required = choice === 'other';
    if (reason.required) notePanel.open = true;
    document.querySelector('#reason-label').textContent = reason.required ? '其他拒绝原因（必填）' : '审核说明（可选）';
    document.querySelector('#decision-hint').textContent = choice === 'approved' ? '已选通过，保存后才会生效。' :
      choice === 'pending' ? '已选暂不判断，保存后保持待审核。' :
      choice === 'other' ? '请填写其他拒绝原因，再保存。' : '已选拒绝，原因会自动记录；可直接保存。';
  };
  reviewForm.querySelectorAll('input[name="decision"]').forEach(input => input.addEventListener('change', updateDecision));
  updateDecision();
  reviewForm.addEventListener('invalid', event => {
    const details = event.target.closest('details');
    if (details) details.open = true;
  }, true);
  const credentials = () => {
    const body = new FormData();
    body.append('csrf', reviewForm.elements.csrf.value);
    body.append('lease', reviewForm.elements.lease.value);
    return body;
  };
  let stopped = false;
  async function renew() {
    if (stopped || document.hidden) return;
    try {
      const response = await fetch(reviewForm.dataset.renew, {method: 'POST', body: credentials()});
      if (!response.ok || response.redirected || !response.headers.get('Content-Type')?.includes('application/json')) {
        stopped = true;
        reviewForm.querySelector('fieldset').disabled = true;
        document.querySelector('.crop-stage').dataset.editable = 'false';
        leaseMessage.textContent = '占用已失效或品类已改派。未保存的内容请先复制，再刷新重新领取。';
      } else {
        leaseMessage.textContent = '你已领取本张照片，停留在本页时自动保留占用。';
      }
    } catch (_error) {
      leaseMessage.textContent = '网络暂时断开，正在重试保留占用；保存时会再次检查。';
    }
  }
  setInterval(renew, 90000);
  document.addEventListener('visibilitychange', renew);
  window.addEventListener('pageshow', event => { if (event.persisted) renew(); });
  window.addEventListener('pagehide', () => {
    navigator.sendBeacon(reviewForm.dataset.release, credentials());
  });
}
