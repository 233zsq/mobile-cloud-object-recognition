'use strict';
const stage = document.querySelector('.crop-stage');
if (stage) {
  const picture = stage.querySelector('img');
  const overlay = stage.querySelector('.crop-box');
  const input = document.querySelector('input[name="crop"]');
  const enabled = document.querySelector('#crop-enabled');
  const clear = document.querySelector('#crop-clear');
  const message = document.querySelector('#crop-message');
  let drag = null;
  const canDraw = () => stage.dataset.editable === 'true' && !enabled.matches(':disabled') && enabled.checked;
  const savedBox = () => input.value ? JSON.parse(input.value) : null;

  function size(box) {
    const width = Number(stage.dataset.width), height = Number(stage.dataset.height);
    // Match the original-pixel bounds used when the server freezes a crop.
    return [Math.ceil(box[2] * width / 10000) - Math.floor(box[0] * width / 10000),
            Math.ceil(box[3] * height / 10000) - Math.floor(box[1] * height / 10000)];
  }
  function show(box) {
    overlay.hidden = !box;
    clear.disabled = !input.value;
    if (!box) { message.textContent = '训练使用完整照片' + (canDraw() ? '；可按住照片拖动框选主体' : ''); return; }
    overlay.style.left = box[0] / 100 + '%';
    overlay.style.top = box[1] / 100 + '%';
    overlay.style.width = (box[2] - box[0]) / 100 + '%';
    overlay.style.height = (box[3] - box[1]) / 100 + '%';
    const [width, height] = size(box);
    message.textContent = `训练使用选框，原图区域 ${width} × ${height} 像素；宽高均需至少128像素`;
  }
  function point(event) {
    const rect = picture.getBoundingClientRect();
    return [Math.max(0, Math.min(10000, Math.round((event.clientX - rect.left) / rect.width * 10000))),
            Math.max(0, Math.min(10000, Math.round((event.clientY - rect.top) / rect.height * 10000)))];
  }
  function cancel() {
    if (!drag) return;
    const id = drag.id;
    drag = null;
    show(savedBox());
    if (stage.hasPointerCapture(id)) stage.releasePointerCapture(id);
  }
  function move(event) {
    if (!drag || event.pointerId !== drag.id) return;
    if (!canDraw()) { cancel(); return; }
    if (!drag.moved && Math.hypot(event.clientX - drag.x, event.clientY - drag.y) < 4) return;
    drag.moved = true;
    const end = point(event);
    drag.box = [Math.min(drag.start[0], end[0]), Math.min(drag.start[1], end[1]),
                Math.max(drag.start[0], end[0]), Math.max(drag.start[1], end[1])];
    show(drag.box);
  }
  stage.addEventListener('pointerdown', event => {
    if (!canDraw() || event.button !== 0 || !event.isPrimary || drag) return;
    event.preventDefault();
    drag = {id: event.pointerId, start: point(event), x: event.clientX, y: event.clientY, moved: false, box: null};
    stage.setPointerCapture(event.pointerId);
  });
  stage.addEventListener('pointermove', move);
  stage.addEventListener('pointerup', event => {
    if (!drag || event.pointerId !== drag.id) return;
    move(event);
    if (!drag) return;
    const {id, moved, box} = drag;
    drag = null;
    if (stage.hasPointerCapture(id)) stage.releasePointerCapture(id);
    if (moved && box) {
      if (size(box).every(length => length >= 128)) {
        input.value = JSON.stringify(box);
      } else {
        show(savedBox());
        message.textContent = '选框太小，宽高均需至少128像素；' + (input.value ? '已保留原选框' : '仍使用完整照片');
        return;
      }
    }
    show(savedBox());
  });
  stage.addEventListener('pointercancel', event => { if (drag && event.pointerId === drag.id) cancel(); });
  stage.addEventListener('lostpointercapture', event => { if (drag && event.pointerId === drag.id) cancel(); });
  enabled.addEventListener('change', () => {
    cancel();
    stage.classList.toggle('selecting', canDraw());
    if (!enabled.checked) input.value = '';
    show(savedBox());
  });
  clear.addEventListener('click', () => {
    if (!canDraw()) return;
    cancel();
    input.value = '';
    show(null);
  });
  stage.classList.toggle('selecting', canDraw());
  show(savedBox());
}
