package com.mobilecloud.recognition.inference

import android.content.Context
import android.graphics.Bitmap
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext

/**
 * 模型仓库：懒加载并缓存 ModelBundle，加载失败可通过 [reload] 重试（用例 T04）。
 * classify 全程不访问网络，断网可用（F02/T03）。
 * 所有公开方法内部切换到 Default 线程：资产读取、Interpreter 初始化与推理都是
 * 同步重计算，禁止在主线程执行。
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

    suspend fun get(): ModelBundle = withContext(Dispatchers.Default) {
        mutex.withLock {
            bundle ?: ModelBundle.load(context.assets).also { bundle = it }
        }
    }

    suspend fun info(): ModelInfo = withContext(Dispatchers.Default) {
        mutex.withLock {
            val target = bundle ?: ModelBundle.load(context.assets).also { bundle = it }
            target.toInfo()
        }
    }

    fun peek(): ModelInfo? = bundle?.toInfo()

    suspend fun classify(bitmap: Bitmap): Prediction = withContext(Dispatchers.Default) {
        val classifier = TfliteClassifier(get())
        classifier.classify(bitmap)
    }

    suspend fun reload(): ModelInfo = withContext(Dispatchers.Default) {
        mutex.withLock {
            bundle?.close()
            bundle = null
            ModelBundle.load(context.assets).let {
                bundle = it
                it.toInfo()
            }
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
