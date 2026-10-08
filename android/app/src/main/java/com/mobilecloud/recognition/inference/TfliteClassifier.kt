package com.mobilecloud.recognition.inference

import android.graphics.Bitmap
import android.os.SystemClock
import com.mobilecloud.recognition.util.PreprocessMath
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * 端侧推理执行器：中心裁剪 → 缩放到模型输入尺寸 → 按 metadata 预设归一化 → LiteRT 推理。
 * 全程在后台线程调用；推理失败向上抛出，由调用方决定提示，不产生伪结果。
 */
class TfliteClassifier(private val bundle: ModelBundle) {

    private val preset = PreprocessMath.NormalizationPreset.fromName(bundle.metadata.input.normalization)
    private val inputSize = bundle.inputSize

    fun classify(source: Bitmap): Prediction {
        val startAll = SystemClock.elapsedRealtime()

        val input = preprocess(source)
        val startInference = SystemClock.elapsedRealtime()

        val scores = runInference(input)
        val endAll = SystemClock.elapsedRealtime()

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
            preprocessMs = startInference - startAll,
            inferenceMs = endAll - startInference,
            totalMs = endAll - startAll,
            modelVersion = bundle.modelVersion,
        )
    }

    private fun preprocess(source: Bitmap): Bitmap {
        val crop = PreprocessMath.centerCropSpec(source.width, source.height)
        val cropped = Bitmap.createBitmap(source, crop.left, crop.top, crop.size, crop.size)
        if (cropped.width == inputSize && cropped.height == inputSize) return cropped
        return Bitmap.createScaledBitmap(cropped, inputSize, inputSize, true)
    }

    private fun runInference(input: Bitmap): FloatArray {
        val pixels = IntArray(inputSize * inputSize)
        input.getPixels(pixels, 0, inputSize, 0, 0, inputSize, inputSize)

        val buffer = ByteBuffer.allocateDirect(1 * inputSize * inputSize * 3 * 4)
            .order(ByteOrder.nativeOrder())
        for (pixel in pixels) {
            buffer.putFloat(preset.apply((pixel shr 16) and 0xFF)) // R
            buffer.putFloat(preset.apply((pixel shr 8) and 0xFF))  // G
            buffer.putFloat(preset.apply(pixel and 0xFF))          // B
        }
        buffer.rewind()

        // LiteRT 按张量形状严格校验数组输出：输出张量是 [1, N]，必须给二维数组
        val output = Array(1) { FloatArray(bundle.outputClasses) }
        bundle.interpreter.run(buffer, output)
        return output[0]
    }
}
