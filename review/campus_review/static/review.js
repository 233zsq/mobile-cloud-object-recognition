'use strict';
const reviewForm = document.querySelector('#review-form');
if (reviewForm && reviewForm.elements.lease.value) {
  const leaseMessage = document.querySelector('#lease-message');
  const reason = reviewForm.elements.reason;
  const requireReason = () => { reason.required = reviewForm.elements.status.value === 'rejected'; };
  reviewForm.elements.status.addEventListener('change', requireReason);
  requireReason();
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
