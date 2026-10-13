package com.mobilecloud.recognition.inference

import android.content.res.AssetManager
import com.mobilecloud.recognition.util.PreprocessMath
import com.mobilecloud.recognition.util.ShaUtil
import java.nio.ByteBuffer
import java.nio.ByteOrder
import org.tensorflow.lite.Interpreter

/**
 * 一次性加载并校验模型包（model.tflite + labels.txt + metadata.json）。
 * 校验失败抛出 [ModelLoadException]，加载失败时上层不得输出任何分类结果（用例 T04）。
 *
 * 标签约定：labels.txt 第 i 行对应输出索引 i，类别 ID 与 shared/categories.json 一致。
 */
class ModelBundle private constructor(
    val interpreter: Interpreter,
    val labels: List<String>,
    val metadata: ModelMetadata,
    val inputShape: IntArray,
    val outputShape: IntArray,
    val modelVersion: String,
    val sha256: String,
    val labelsSha256: String,
    val lowConfidenceThreshold: Float,
    /** 归一化约定：正式契约在模型内部，端侧为恒等（原始 0–255） */
    val normalization: PreprocessMath.NormalizationPreset,
    /** metadata.json 中 input 段的原始 JSON，端云一致性报告须原样嵌入（校验器逐字段比对） */
    val inputContract: kotlinx.serialization.json.JsonElement?,
    /** 解释器实际线程数，报告 runtime 字段使用 */
    val numThreads: Int,
    val scopePolicy: ScopePolicyState,
    val assetDirectory: String,
) {
    /** 正方形输入边长（如 224），预处理直接使用 */
    val inputSize: Int = inputShape[1]

    /** 输出类别数 */
    val outputClasses: Int = outputShape.last()

    fun close() {
        interpreter.close()
    }

    companion object {
        /** 兜底阈值；正式包由 metadata.low_confidence_threshold 提供（契约 campus-gpu-v1 为 0.5） */
        const val DEFAULT_THRESHOLD = 0.5f
        fun load(assets: AssetManager, directory: String = "models"): ModelBundle {
            require(directory == "models" || directory == "models/campus-evolve-v2")
            val MODEL_DIR = directory
            val metadataText = readAssetText(assets, "$MODEL_DIR/metadata.json")
            val metadata = ModelMetadata.parse(metadataText)
            val inputContract = runCatching {
                ModelMetadata.json.parseToJsonElement(metadataText)
                    .let { it as? kotlinx.serialization.json.JsonObject }
                    ?.get("input")
            }.getOrNull()

            val modelBytes = readAsset(assets, "$MODEL_DIR/${metadata.modelFile}")
            val modelSha = ShaUtil.sha256Hex(modelBytes)
            metadata.sha256?.takeIf { it.isNotBlank() }?.let { expected ->
                checkSha(expected, modelSha, "model.tflite")
            }

            val labelsText = readAssetText(assets, "$MODEL_DIR/${metadata.labelsFile}")
            val labelsSha = ShaUtil.sha256Hex(labelsText.toByteArray(Charsets.UTF_8))
            metadata.labelsSha256?.takeIf { it.isNotBlank() }?.let { expected ->
                checkSha(expected, labelsSha, "labels.txt")
            }
            val labels = parseLabels(labelsText)

            val buffer = ByteBuffer.allocateDirect(modelBytes.size).order(ByteOrder.nativeOrder())
            buffer.put(modelBytes)
            buffer.rewind()

            val options = Interpreter.Options().apply {
                numThreads = Runtime.getRuntime().availableProcessors().coerceIn(1, 4)
            }
            val threadCount = options.numThreads
            val interpreter = try {
                Interpreter(buffer, options)
            } catch (e: Exception) {
                throw ModelLoadException("模型初始化失败，文件可能损坏：${e.message}", e)
            }

            try {
                require(interpreter.inputTensorCount == 1) { "模型必须只有一个输入" }
                val count = interpreter.outputTensorCount
                require(metadata.scoreOutputIndex in 0 until count) { "分类输出位置无效" }
                metadata.scopeOutput?.let { scope ->
                    require(count == 2 && scope.index in 0 until count && scope.index != metadata.scoreOutputIndex &&
                        scope.shape == listOf(1, 1) && scope.dtype == "float32" && scope.interpretation == "knownness") { "范围输出契约无效" }
                    val tensor = interpreter.getOutputTensor(scope.index)
                    require(tensor.shape().contentEquals(intArrayOf(1, 1)) && dtypeName(tensor.dataType()) == "float32") { "范围输出张量不符" }
                } ?: require(count == 1 && metadata.scoreOutputIndex == 0) { "存在未声明的模型输出" }
                require(dtypeName(interpreter.getOutputTensor(metadata.scoreOutputIndex).dataType()) == "float32") { "分类输出必须为 float32" }
            } catch (e: Exception) {
                interpreter.close()
                throw ModelLoadException("模型输出校验失败：${e.message}", e)
            }
            val inputTensor = interpreter.getInputTensor(0)
            val outputTensor = interpreter.getOutputTensor(metadata.scoreOutputIndex)
            val inputShape = inputTensor.shape()
            val outputShape = outputTensor.shape()

            val errors = ModelValidator.validate(
                inputShape = inputShape,
                inputDtype = dtypeName(inputTensor.dataType()),
                outputShape = outputShape,
                labels = labels,
                metadata = metadata,
            )
            if (errors.isNotEmpty()) {
                interpreter.close()
                throw ModelLoadException(errors.joinToString("；"))
            }

            // 校验已通过，归一化约定必然可解析
            val normalization = PreprocessMath.NormalizationPreset.fromName(metadata.input.normalization)

            return ModelBundle(
                interpreter = interpreter,
                labels = labels,
                metadata = metadata,
                inputShape = inputShape,
                outputShape = outputShape,
                modelVersion = metadata.modelVersion!!,
                sha256 = modelSha,
                labelsSha256 = labelsSha,
                lowConfidenceThreshold = metadata.lowConfidenceThreshold ?: DEFAULT_THRESHOLD,
                normalization = normalization,
                inputContract = inputContract,
                numThreads = threadCount,
                assetDirectory = directory,
                scopePolicy = try {
                    val policyFile = metadata.scopePolicyFile
                    require(policyFile == null || policyFile.matches(Regex("[A-Za-z0-9._-]+")))
                    val policyPath = if (policyFile == null) "scope/scope-policy.json" else "$MODEL_DIR/$policyFile"
                    ScopePolicyState.parse(readAsset(assets, policyPath),
                        metadata.scopePolicySha256 ?: readAssetText(assets, "scope/scope-policy.sha256"),
                        ScopeIdentity(metadata.modelVersion!!, modelSha, labelsSha, metadata.categoryVersion, metadata.input.version))
                } catch (_: Exception) { ScopePolicyState.unavailable },
            )
        }

        fun parseLabels(text: String): List<String> =
            text.lines().map { it.trim() }.filter { it.isNotEmpty() }

        fun dtypeName(dataType: Any?): String = dataType?.toString()?.lowercase() ?: "unknown"

        private fun readAsset(assets: AssetManager, path: String): ByteArray = try {
            assets.open(path).use { it.readBytes() }
        } catch (e: Exception) {
            throw ModelLoadException("缺少模型包文件 $path，请按 docs/model-contract.md 放置模型", e)
        }

        private fun readAssetText(assets: AssetManager, path: String): String =
            String(readAsset(assets, path), Charsets.UTF_8)

        private fun checkSha(expected: String, actual: String, file: String) {
            if (!expected.equals(actual, ignoreCase = true)) {
                throw ModelLoadException("$file SHA-256 不一致，模型包可能混用版本：期望 $expected，实际 $actual")
            }
        }
    }
}
