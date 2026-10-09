'use strict';
const stage = document.querySelector('.crop-stage');
if (stage) {
  const picture = stage.querySelector('img');
  const overlay = stage.querySelector('.crop-box');
  const input = document.querySelector('input[name="crop"]');
  const enabled = document.querySelector('#crop-enabled');
  const message = document.querySelector('#crop-message');
  let anchor = null;
  function show(box) {
    overlay.hidden = !box;
    if (!box) { message.textContent = '训练使用完整照片'; return; }
    overlay.style.left = box[0] / 100 + '%';
    overlay.style.top = box[1] / 100 + '%';
    overlay.style.width = (box[2] - box[0]) / 100 + '%';
    overlay.style.height = (box[3] - box[1]) / 100 + '%';
    const w = Math.ceil((box[2] - box[0]) * Number(stage.dataset.width) / 10000);
    const h = Math.ceil((box[3] - box[1]) * Number(stage.dataset.height) / 10000);
    message.textContent = `训练使用选框，原图区域约 ${w} × ${h} 像素；宽高均需至少128像素`;
  }
  function point(event) {
    const rect = picture.getBoundingClientRect();
    return [Math.max(0, Math.min(10000, Math.round((event.clientX - rect.left) / rect.width * 10000))),
            Math.max(0, Math.min(10000, Math.round((event.clientY - rect.top) / rect.height * 10000)))];
  }
  function move(event) {
    if (!anchor) return;
    const end = point(event);
    const box = [Math.min(anchor[0], end[0]), Math.min(anchor[1], end[1]),
                 Math.max(anchor[0], end[0]), Math.max(anchor[1], end[1])];
    input.value = JSON.stringify(box); show(box);
  }
  stage.addEventListener('pointerdown', event => {
    if (stage.dataset.editable !== 'true' || !enabled.checked || event.button !== 0) return;
    event.preventDefault(); anchor = point(event); stage.setPointerCapture(event.pointerId);
  });
  stage.addEventListener('pointermove', move);
  stage.addEventListener('pointerup', event => { move(event); anchor = null; });
  stage.addEventListener('pointercancel', () => { anchor = null; });
  enabled.addEventListener('change', () => {
    stage.classList.toggle('selecting', enabled.checked);
    if (!enabled.checked) { input.value = ''; show(null); }
  });
  document.querySelector('#review-form').addEventListener('submit', event => {
    if (enabled.checked && !input.value) {
      event.preventDefault(); message.textContent = '请先在照片上拖动选框，或取消勾选以使用全图';
    }
  });
  stage.classList.toggle('selecting', enabled.checked);
  show(input.value ? JSON.parse(input.value) : null);
}
