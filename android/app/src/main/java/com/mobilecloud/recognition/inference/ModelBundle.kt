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
) {
    /** 正方形输入边长（如 224），预处理直接使用 */
    val inputSize: Int = inputShape[1]

    /** 输出类别数 */
    val outputClasses: Int = outputShape.last()

    fun close() {
        interpreter.close()
    }

    companion object {
        const val DEFAULT_THRESHOLD = 0.60f
        private const val MODEL_DIR = "models"

        fun load(assets: AssetManager): ModelBundle {
            val metadata = readMetadata(assets)

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
            val interpreter = try {
                Interpreter(buffer, options)
            } catch (e: Exception) {
                throw ModelLoadException("模型初始化失败，文件可能损坏：${e.message}", e)
            }

            val inputTensor = interpreter.getInputTensor(0)
            val outputTensor = interpreter.getOutputTensor(0)
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
            )
        }

        fun parseLabels(text: String): List<String> =
            text.lines().map { it.trim() }.filter { it.isNotEmpty() }

        fun dtypeName(dataType: Any?): String = dataType?.toString()?.lowercase() ?: "unknown"

        private fun readMetadata(assets: AssetManager): ModelMetadata {
            val text = readAssetText(assets, "$MODEL_DIR/metadata.json")
            return ModelMetadata.parse(text)
        }

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
