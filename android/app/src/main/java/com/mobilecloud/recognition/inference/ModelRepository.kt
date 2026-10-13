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
    private val preferences = context.getSharedPreferences("local-model-selection", Context.MODE_PRIVATE)
    val versions = listOf("campus-evolve-v3", "campus-evolve-v2")

    private fun loadSelected(): ModelBundle {
        val version = preferences.getString("version", null)?.takeIf { it in versions } ?: versions.first()
        return loadVersion(version)
    }

    private fun loadVersion(version: String): ModelBundle {
        require(version in versions) { "未知本地模型" }
        val loaded = ModelBundle.load(context.assets, if (version == "campus-evolve-v2") "models/campus-evolve-v2" else "models")
        if (loaded.modelVersion != version || loaded.scopePolicy.policy == null) {
            loaded.close()
            error("本地模型或范围规则不匹配")
        }
        return loaded
    }

    suspend fun selectVersion(version: String): ModelInfo = withContext(Dispatchers.Default) {
        mutex.withLock {
            val next = loadVersion(version)
            if (!preferences.edit().putString("version", version).commit()) {
                next.close()
                error("无法保存本地模型选择")
            }
            bundle?.close()
            bundle = next
            next.toInfo()
        }
    }

    data class ModelInfo(
        val modelVersion: String,
        val sha256Short: String,
        val labelsCount: Int,
        val inputShape: IntArray,
        val lowConfidenceThreshold: Float,
        val categoryVersion: String?,
        val normalization: String,
        val scopePolicyVersion: String? = null,
        val scopePolicySha256: String? = null,
        val scopeKnownnessThreshold: Float? = null,
        val scopeConfidenceThreshold: Float? = null,
        val scopeMarginThreshold: Float? = null,
    )

    suspend fun info(): ModelInfo = withContext(Dispatchers.Default) {
        mutex.withLock {
            val target = bundle ?: loadSelected().also { bundle = it }
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
            val target = bundle ?: loadSelected().also { bundle = it }
            TfliteClassifier(target).classify(bitmap)
        }
    }

    /** Preview must never queue behind model reload, consistency checks or a saved-photo inference. */
    suspend fun tryClassifyPreview(bitmap: Bitmap): Prediction? = withContext(Dispatchers.Default) {
        if (!mutex.tryLock()) return@withContext null
        try {
            val target = bundle ?: return@withContext null
            TfliteClassifier(target).classify(bitmap)
        } finally { mutex.unlock() }
    }

    /** 在持锁状态下使用模型包（一致性自检等长任务专用），期间 reload 会等待其结束 */
    suspend fun <T> withBundle(block: suspend (ModelBundle) -> T): T = withContext(Dispatchers.Default) {
        mutex.withLock {
            val target = bundle ?: loadSelected().also { bundle = it }
            block(target)
        }
    }

    suspend fun reload(): ModelInfo = withContext(Dispatchers.Default) {
        mutex.withLock {
            bundle?.close()
            bundle = null
            loadSelected().let {
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
        scopePolicyVersion = scopePolicy.policy?.version,
        scopePolicySha256 = scopePolicy.sha256,
        scopeKnownnessThreshold = scopePolicy.policy?.knownnessThreshold,
        scopeConfidenceThreshold = scopePolicy.policy?.confidenceThreshold,
        scopeMarginThreshold = scopePolicy.policy?.marginThreshold,
    )
}
