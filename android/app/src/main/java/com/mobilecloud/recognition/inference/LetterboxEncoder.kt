package com.mobilecloud.recognition.inference

import android.graphics.Bitmap
import com.mobilecloud.recognition.util.PreprocessMath
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.floor

/**
 * 契约 `rgb-letterbox-v1` 的输入编码器：等比 half-pixel 双线性缩放 + 灰色128居中补边，
 * 四邻域加权保留 float32 直接写入 little-endian 连续 NHWC 缓冲（602112 字节）。
 * 推理与端云一致性自检共用同一实现，保证"同图同输入"。
 */
object LetterboxEncoder {

    /** 契约固定字节数：224 × 224 × 3 × 4 */
    const val CONTRACT_BYTES = 224 * 224 * 3 * 4

    fun encode(
        source: Bitmap,
        target: Int,
        preset: PreprocessMath.NormalizationPreset,
    ): ByteBuffer {
        val srcWidth = source.width
        val srcHeight = source.height
        val geometry = PreprocessMath.letterboxGeometry(srcWidth, srcHeight, target)

        val srcPixels = IntArray(srcWidth * srcHeight)
        source.getPixels(srcPixels, 0, srcWidth, 0, 0, srcWidth, srcHeight)

        val buffer = ByteBuffer.allocateDirect(1 * target * target * 3 * 4)
            .order(ByteOrder.LITTLE_ENDIAN)
        val padValue = preset.apply(PreprocessMath.PAD_VALUE)

        val colSrc = FloatArray(geometry.innerWidth) { x ->
            PreprocessMath.halfPixelSourceCoord(x, geometry.innerWidth, srcWidth)
        }
        val rowSrc = FloatArray(geometry.innerHeight) { y ->
            PreprocessMath.halfPixelSourceCoord(y, geometry.innerHeight, srcHeight)
        }

        for (y in 0 until target) {
            val innerY = y - geometry.offsetY
            if (innerY < 0 || innerY >= geometry.innerHeight) {
                repeat(target) {
                    buffer.putFloat(padValue); buffer.putFloat(padValue); buffer.putFloat(padValue)
                }
                continue
            }
            val sy = rowSrc[innerY]
            val y0 = floor(sy).toInt()
            val fy = sy - y0
            val y0c = y0.coerceIn(0, srcHeight - 1)
            val y1c = (y0 + 1).coerceIn(0, srcHeight - 1)
            val rowOffset0 = y0c * srcWidth
            val rowOffset1 = y1c * srcWidth

            for (x in 0 until target) {
                val innerX = x - geometry.offsetX
                if (innerX < 0 || innerX >= geometry.innerWidth) {
                    buffer.putFloat(padValue); buffer.putFloat(padValue); buffer.putFloat(padValue)
                    continue
                }
                val sx = colSrc[innerX]
                val x0 = floor(sx).toInt()
                val fx = sx - x0
                val x0c = x0.coerceIn(0, srcWidth - 1)
                val x1c = (x0 + 1).coerceIn(0, srcWidth - 1)

                val p00 = srcPixels[rowOffset0 + x0c]
                val p10 = srcPixels[rowOffset0 + x1c]
                val p01 = srcPixels[rowOffset1 + x0c]
                val p11 = srcPixels[rowOffset1 + x1c]

                buffer.putFloat(preset.apply(PreprocessMath.bilinearSample(r(p00), r(p10), r(p01), r(p11), fx, fy)))
                buffer.putFloat(preset.apply(PreprocessMath.bilinearSample(g(p00), g(p10), g(p01), g(p11), fx, fy)))
                buffer.putFloat(preset.apply(PreprocessMath.bilinearSample(b(p00), b(p10), b(p01), b(p11), fx, fy)))
            }
        }
        buffer.rewind()
        return buffer
    }

    private fun r(pixel: Int): Float = ((pixel shr 16) and 0xFF).toFloat()
    private fun g(pixel: Int): Float = ((pixel shr 8) and 0xFF).toFloat()
    private fun b(pixel: Int): Float = (pixel and 0xFF).toFloat()
}