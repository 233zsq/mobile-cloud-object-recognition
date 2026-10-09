package com.mobilecloud.recognition.inference

import android.graphics.Bitmap
import android.os.SystemClock
import com.mobilecloud.recognition.util.PreprocessMath
import java.nio.ByteBuffer

/**
 * 端侧推理执行器，实现契约 `rgb-letterbox-v1` 的输入链路
 * （docs/ml-handover.md「手机与云端共同输入」）：
 *
 * 1. 输入源须为 EXIF 已纠正的直立图（见 PhotoStore）；
 * 2. 输入编码统一走 [LetterboxEncoder]（等比 half-pixel 双线性 + 灰色128居中补边）；
 * 3. 归一化按 metadata 约定（正式契约在模型内部，端侧恒等）。
 *
 * 全程在后台线程调用（ModelRepository 负责调度）；失败向上抛出，不产生伪结果。
 * 计时口径：preprocessMs 覆盖缩放到输入缓冲就绪（含像素编码），inferenceMs 只覆盖 interpreter.run。
 */
class TfliteClassifier(private val bundle: ModelBundle) {

    fun classify(source: Bitmap): Prediction {
        val startAll = SystemClock.elapsedRealtime()

        val input = LetterboxEncoder.encode(source, bundle.inputSize, bundle.normalization)
        val inputReady = SystemClock.elapsedRealtime()

        val scores = runInterpreter(input)
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
            preprocessMs = inputReady - startAll,
            inferenceMs = endAll - inputReady,
            totalMs = endAll - startAll,
            modelVersion = bundle.modelVersion,
        )
    }

    /** 对已编码的契约输入执行推理；供一致性自检复用（与推理链路同一张量入口） */
    fun runInterpreter(input: ByteBuffer): FloatArray {
        val output = Array(1) { FloatArray(bundle.outputClasses) }
        bundle.interpreter.run(input, output)
        return output[0]
    }
}