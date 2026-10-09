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
        val normalization: String,
    )

    suspend fun info(): ModelInfo = withContext(Dispatchers.Default) {
        mutex.withLock {
            val target = bundle ?: ModelBundle.load(context.assets).also { bundle = it }
            target.toInfo()
        }
    }

    fun peek(): ModelInfo? = bundle?.toInfo()

    /**
     * 推理全程持有与 [reload] 相同的锁：重载必须等待在途推理结束，
     * 避免 `bundle.close()` 释放在用的 Interpreter（原生资源访问崩溃）。
     */
    suspend fun classify(bitmap: Bitmap): Prediction = withContext(Dispatchers.Default) {
        mutex.withLock {
            val target = bundle ?: ModelBundle.load(context.assets).also { bundle = it }
            TfliteClassifier(target).classify(bitmap)
        }
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
        normalization = metadata.input.normalization ?: "identity",
    )
}
