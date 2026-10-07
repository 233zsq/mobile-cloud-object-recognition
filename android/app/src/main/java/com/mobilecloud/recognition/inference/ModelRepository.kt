package com.mobilecloud.recognition.inference

import android.content.Context
import android.graphics.Bitmap
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/**
 * 模型仓库：懒加载并缓存 ModelBundle，加载失败可通过 [reload] 重试（用例 T04）。
 * classify 全程不访问网络，断网可用（F02/T03）。
 */
class ModelRepository(private val context: Context) {

    private val mutex = Mutex()
    private var bundle: ModelBundle? = null

    data class ModelInfo(
        val modelVersion: String,
        val sha256Short: String,
        val labelsCount: Int,
        val inputShape: IntArray,
        val lowConfidenceThreshold: Float,
        val categoryVersion: String?,
    )

    suspend fun get(): ModelBundle = mutex.withLock {
        bundle ?: ModelBundle.load(context.assets).also { bundle = it }
    }

    suspend fun info(): ModelInfo = mutex.withLock {
        val target = bundle ?: ModelBundle.load(context.assets).also { bundle = it }
        target.toInfo()
    }

    fun peek(): ModelInfo? = bundle?.toInfo()

    suspend fun classify(bitmap: Bitmap): Prediction {
        val classifier = TfliteClassifier(get())
        return classifier.classify(bitmap)
    }

    suspend fun reload(): ModelInfo = mutex.withLock {
        bundle?.close()
        bundle = null
        ModelBundle.load(context.assets).let {
            bundle = it
            it.toInfo()
        }
    }

    private fun ModelBundle.toInfo() = ModelInfo(
        modelVersion = modelVersion,
        sha256Short = sha256.take(8),
        labelsCount = labels.size,
        inputShape = inputShape,
        lowConfidenceThreshold = lowConfidenceThreshold,
        categoryVersion = metadata.categoryVersion,
    )
}
