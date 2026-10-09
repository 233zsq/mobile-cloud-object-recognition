package com.mobilecloud.recognition.inference

import android.content.Context
import android.os.Build
import com.mobilecloud.recognition.camera.decodeAssetUpright
import com.mobilecloud.recognition.util.ShaUtil
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json

/**
 * 端云一致性自检（T05 / 交接用例 M02–M04）：对发布包附带的 20 张样例分别执行
 * - reference_tensor 模式：直接喂 examples 目录下的参考张量文件；
 * - image_chain 模式：从图片走端侧预处理（EXIF→letterbox→灰底补边→恒等直传）生成输入。
 *
 * 两种模式的输入都通过 [TfliteClassifier.runInterpreter] 进入同一个解释器实例，
 * 与日常推理链路共用 [LetterboxEncoder]。产物写入应用外部私有目录的
 * consistency/<runId>/，并打包为 zip 供分享；正式判定由仓库的
 * `python -m recognition verify --external-report` 完成（本类只做本地自评）。
 */
class ConsistencyCheck(private val context: Context) {

    data class ReportOutcome(
        val mode: String,
        val passed: Int,
        val total: Int,
        val failures: List<String>,
    )

    data class Summary(
        val runId: String,
        val device: String,
        val runtime: String,
        val outputDir: File,
        val zipFile: File,
        val reference: ReportOutcome,
        val imageChain: ReportOutcome,
    ) {
        val allPassed: Boolean
            get() = reference.passed == reference.total && imageChain.passed == imageChain.total
    }

    suspend fun run(bundle: ModelBundle, onProgress: (String) -> Unit): Summary =
        withContext(Dispatchers.Default) {
            val assets = context.assets
            val contract = bundle.inputContract
                ?: throw IllegalStateException("metadata 缺少 input 段，无法生成一致性报告")
            if (bundle.inputSize != 224) {
                throw IllegalStateException("自检样例按 224×224 契约准备，当前模型输入 ${bundle.inputSize}，无法对照")
            }

            val manifestText = assets.open("$EXAMPLES_DIR/manifest.json")
                .use { String(it.readBytes(), Charsets.UTF_8) }
            val samples = ExampleSample.parse(manifestText)
            require(samples.isNotEmpty()) { "样例清单为空" }

            val runId = buildRunId()
            // 交接约定：每份报告使用不同的 run_id（团队既有记录为 ...-image_chain / ...-reference_tensor 后缀），
            // 否则校验器在第二份报告时报 "Consistency evidence exists"
            val referenceRunId = ConsistencyReport.runIdFor(runId, ConsistencyReport.MODE_REFERENCE_TENSOR)
            val imageRunId = ConsistencyReport.runIdFor(runId, ConsistencyReport.MODE_IMAGE_CHAIN)
            val outputDir = File(context.getExternalFilesDir(null), "consistency/$runId").apply { mkdirs() }
            val device = deviceLabel()
            val runtime = runtimeLabel(bundle.numThreads)
            val classifier = TfliteClassifier(bundle)
            val json = Json { prettyPrint = true }

            // ---- reference_tensor：直接喂参考张量 ----
            val refSamples = mutableListOf<ConsistencyReport.SampleReport>()
            val refFailures = mutableListOf<String>()
            samples.forEachIndexed { index, sample ->
                onProgress("参考张量 ${index + 1}/${samples.size}：${sample.sampleId}")
                val bytes = assets.open("$EXAMPLES_DIR/${sample.tensor}").use { it.readBytes() }
                require(bytes.size == LetterboxEncoder.CONTRACT_BYTES) {
                    "参考张量 ${sample.tensor} 字节数 ${bytes.size} 与契约不符"
                }
                val buffer = ByteBuffer.allocateDirect(bytes.size).order(ByteOrder.LITTLE_ENDIAN)
                    .apply { put(bytes); rewind() }
                val scores = classifier.runInterpreter(buffer)
                val sha = ShaUtil.sha256Hex(bytes)
                val verdict = ConsistencyReport.evaluate(scores, sample.scores, sample.predictedId, null)
                if (!verdict.passed || (sample.tensorSha256 != null && sha != sample.tensorSha256)) {
                    refFailures += "${sample.sampleId}: top1=${verdict.top1Same} scoreDiff=${"%.6g".format(verdict.maxScoreDiff)}"
                }
                refSamples += ConsistencyReport.SampleReport(
                    sampleId = sample.sampleId,
                    scores = scores,
                    tensorSha256 = sha,
                )
            }
            val refReport = ConsistencyReport.build(
                mode = ConsistencyReport.MODE_REFERENCE_TENSOR,
                runId = referenceRunId,
                device = device,
                runtime = runtime,
                modelSha256 = bundle.sha256,
                labelsSha256 = bundle.labelsSha256,
                inputContract = contract,
                samples = refSamples,
            )
            File(outputDir, "$runId-reference_tensor.json")
                .writeText(json.encodeToString(kotlinx.serialization.json.JsonObject.serializer(), refReport))

            // ---- image_chain：从图片走端侧预处理 ----
            val imgSamples = mutableListOf<ConsistencyReport.SampleReport>()
            val imgFailures = mutableListOf<String>()
            samples.forEachIndexed { index, sample ->
                onProgress("图片链路 ${index + 1}/${samples.size}：${sample.sampleId}")
                val bitmap = decodeAssetUpright(context, "$EXAMPLES_DIR/${sample.image}")
                    ?: throw IllegalStateException("样例图片 ${sample.image} 解码失败")
                val buffer = LetterboxEncoder.encode(bitmap, bundle.inputSize, bundle.normalization)
                bitmap.recycle()
                val produced = ByteArray(buffer.capacity())
                buffer.duplicate().get(produced)
                buffer.rewind()
                File(outputDir, "${sample.sampleId}.bin").writeBytes(produced)

                val scores = classifier.runInterpreter(buffer)
                val golden = assets.open("$EXAMPLES_DIR/${sample.tensor}").use { it.readBytes() }
                val inputDiff = ConsistencyReport.maxFloatDiff(produced, golden)
                val (minV, maxV) = ConsistencyReport.floatRange(produced)
                val verdict = ConsistencyReport.evaluate(scores, sample.scores, sample.predictedId, inputDiff)
                if (!verdict.passed || minV < 0f || maxV > 255f) {
                    imgFailures += "${sample.sampleId}: inputDiff=${"%.6g".format(inputDiff)} top1=${verdict.top1Same} " +
                        "scoreDiff=${"%.6g".format(verdict.maxScoreDiff)} range=[$minV,$maxV]"
                }
                imgSamples += ConsistencyReport.SampleReport(
                    sampleId = sample.sampleId,
                    scores = scores,
                    tensorFile = "${sample.sampleId}.bin",
                )
            }
            val imgReport = ConsistencyReport.build(
                mode = ConsistencyReport.MODE_IMAGE_CHAIN,
                runId = imageRunId,
                device = device,
                runtime = runtime,
                modelSha256 = bundle.sha256,
                labelsSha256 = bundle.labelsSha256,
                inputContract = contract,
                samples = imgSamples,
            )
            File(outputDir, "$runId-image_chain.json")
                .writeText(json.encodeToString(kotlinx.serialization.json.JsonObject.serializer(), imgReport))

            // ---- 打包（两份报告 + 图片链路张量） ----
            val zipFile = File(outputDir, "$runId-consistency.zip")
            ZipOutputStream(zipFile.outputStream().buffered()).use { zip ->
                outputDir.listFiles()?.sortedBy { it.name }?.forEach { file ->
                    if (file.isFile && file.extension != "zip") {
                        zip.putNextEntry(ZipEntry(file.name))
                        file.inputStream().use { it.copyTo(zip) }
                        zip.closeEntry()
                    }
                }
            }

            Summary(
                runId = runId,
                device = device,
                runtime = runtime,
                outputDir = outputDir,
                zipFile = zipFile,
                reference = ReportOutcome(
                    mode = ConsistencyReport.MODE_REFERENCE_TENSOR,
                    passed = samples.size - refFailures.size,
                    total = samples.size,
                    failures = refFailures,
                ),
                imageChain = ReportOutcome(
                    mode = ConsistencyReport.MODE_IMAGE_CHAIN,
                    passed = samples.size - imgFailures.size,
                    total = samples.size,
                    failures = imgFailures,
                ),
            )
        }

    fun hasExamples(): Boolean = runCatching {
        context.assets.open("$EXAMPLES_DIR/manifest.json").use { }
        true
    }.getOrDefault(false)

    private fun buildRunId(): String {
        val model = Build.MODEL.replace(Regex("[^A-Za-z0-9]"), "-").trim('-').ifEmpty { "device" }
        val stamp = SimpleDateFormat("yyyyMMdd-HHmmss", Locale.US).format(Date())
        // run_id 只允许字母、数字、_ 与 -（recognition.common.safe_name）
        return "android-$model-$stamp"
    }

    private fun deviceLabel(): String =
        "${Build.MANUFACTURER} ${Build.MODEL} / Android ${Build.VERSION.RELEASE} (SDK ${Build.VERSION.SDK_INT})"

    private fun runtimeLabel(threads: Int): String =
        "LiteRT java org.tensorflow.lite 1.4.1 / threads=$threads"

    companion object {
        const val EXAMPLES_DIR = "models/examples"
    }
}