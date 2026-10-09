package com.mobilecloud.recognition.inference

import android.content.res.AssetManager
import android.graphics.Bitmap
import android.os.SystemClock
import com.mobilecloud.recognition.util.PreprocessMath
import com.mobilecloud.recognition.util.ShaUtil
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.floor
import org.tensorflow.lite.Interpreter

/**
 * 端侧推理执行器，实现契约 `rgb-letterbox-v1` 的输入链路
 * （docs/ml-handover.md「手机与云端共同输入」）：
 *
 * 1. 输入源须为 EXIF 已纠正的直立图（见 PhotoStore）；
 * 2. 等比缩放至 letterbox 内框（双线性、half-pixel 坐标、不额外抗锯齿）；
 * 3. 灰色 128 居中补边至模型输入边长，奇数余量位于右/下，不裁剪；
 * 4. 四邻域加权结果保留 float32 直接写入输入缓冲，不先取整为 uint8；
 * 5. 归一化按 metadata 约定（正式契约在模型内部，端侧恒等）。
 *
 * 全程在后台线程调用（ModelRepository 负责调度）；失败向上抛出，不产生伪结果。
 * 计时口径：preprocessMs 覆盖缩放到输入缓冲就绪（含像素编码），inferenceMs 只覆盖 interpreter.run。
 */
class TfliteClassifier(private val bundle: ModelBundle) {

    private val inputSize = bundle.inputSize

    fun classify(source: Bitmap): Prediction {
        val startAll = SystemClock.elapsedRealtime()

        val input = encodeLetterboxInput(source)
        val inputReady = SystemClock.elapsedRealtime()

        // LiteRT 按张量形状严格校验数组输出：输出张量是 [1, N]，必须给二维数组
        val output = Array(1) { FloatArray(bundle.outputClasses) }
        bundle.interpreter.run(input, output)
        val endAll = SystemClock.elapsedRealtime()

        val scores = output[0]
        var bestIndex = -1
        var bestScore = Float.NEGATIVE_INFINITY
        for (i in scores.indices) {
            if (scores[i] > bestScore) {
                bestScore = scores[i]
                bestIndex = i
            }
        }
        if (bestIndex < 0) throw IllegalStateException("模型输出为空，无法产生分类结果")

        return Prediction(
            index = bestIndex,
            confidence = bestScore,
            label = bundle.labels.getOrElse(bestIndex) { bestIndex.toString() },
            preprocessMs = inputReady - startAll,
            inferenceMs = endAll - inputReady,
            totalMs = endAll - startAll,
            modelVersion = bundle.modelVersion,
        )
    }

    private fun encodeLetterboxInput(source: Bitmap): ByteBuffer {
        val srcWidth = source.width
        val srcHeight = source.height
        val target = inputSize
        val geometry = PreprocessMath.letterboxGeometry(srcWidth, srcHeight, target)

        val srcPixels = IntArray(srcWidth * srcHeight)
        source.getPixels(srcPixels, 0, srcWidth, 0, 0, srcWidth, srcHeight)

        // 契约要求 little-endian float32 连续 NHWC（224*224*3*4 = 602112 字节）
        val buffer = ByteBuffer.allocateDirect(1 * target * target * 3 * 4)
            .order(ByteOrder.LITTLE_ENDIAN)
        val preset = bundle.normalization
        val padValue = preset.apply(PreprocessMath.PAD_VALUE)

        // 预计算列/行源坐标与权重，避免内层重复计算
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