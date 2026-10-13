import { ApiFailure } from './api.js';
import { MAX_SOURCE_BYTES, TRANSFER_MAX_SIDE, TRANSFER_QUALITY, TRANSFER_MAX_BYTES } from './state.js';

export function loadImage(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const image = new Image();
    image.onload = () => resolve({ image, url });
    // 不使用 image.decode()：在部分浏览器/WebView 上该 Promise 不返回，会让识别流程整体卡住；
    // onload 已保证图片可绘制。
    image.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new ApiFailure('IMAGE_DECODE', '无法读取这张图片，请重新拍照，或在相册中导出 JPEG / PNG 后重试。', 0));
    };
    image.src = url;
  });
}

export function canvasToBlob(canvas, quality) {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) resolve(blob);
      else reject(new ApiFailure('IMAGE_DECODE', '图片处理失败，请重试。', 0));
    }, 'image/jpeg', quality);
  });
}

export async function makeTransferCopy(file) {
  if (file.size > MAX_SOURCE_BYTES) {
    throw new ApiFailure('IMAGE_TOO_LARGE', '原图超过 32 MiB，请重新拍摄或选择更小的图片。', 0);
  }
  const { image, url } = await loadImage(file);
  let canvas;
  try {
    const width = image.naturalWidth || image.width;
    const height = image.naturalHeight || image.height;
    if (!width || !height) {
      throw new ApiFailure('IMAGE_DECODE', '无法读取这张图片，请重新拍照或换一张。', 0);
    }
    const scale = Math.min(1, TRANSFER_MAX_SIDE / Math.max(width, height));
    canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(width * scale));
    canvas.height = Math.max(1, Math.round(height * scale));
    const context = canvas.getContext('2d');
    if (!context) throw new ApiFailure('IMAGE_DECODE', '这个浏览器无法处理图片，请换用系统浏览器打开。', 0);
    context.fillStyle = '#808080';
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
  } finally {
    URL.revokeObjectURL(url);          // 绘制完成后即可释放，避免 Safari 重新取图失败
  }
  let quality = TRANSFER_QUALITY;
  let blob = await canvasToBlob(canvas, quality);
  while (blob.size > TRANSFER_MAX_BYTES && quality > 0.5) {
    quality = Math.round((quality - 0.1) * 100) / 100;
    blob = await canvasToBlob(canvas, quality);
  }
  if (blob.size > TRANSFER_MAX_BYTES) {
    throw new ApiFailure('IMAGE_TOO_LARGE', '图片压缩后仍然过大，请换一张更小的图片。', 0);
  }
  return blob;
}
