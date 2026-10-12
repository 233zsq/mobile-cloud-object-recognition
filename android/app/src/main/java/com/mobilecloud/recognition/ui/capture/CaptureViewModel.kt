package com.mobilecloud.recognition.ui.capture

import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.mobilecloud.recognition.AppGraph
import com.mobilecloud.recognition.data.local.RecordEntity
import com.mobilecloud.recognition.inference.ModelRepository
import com.mobilecloud.recognition.inference.Prediction
import com.mobilecloud.recognition.inference.CloudClassifier
import com.mobilecloud.recognition.inference.CloudModelContract
import com.mobilecloud.recognition.inference.ModelMetadata
import com.mobilecloud.recognition.util.ShaUtil
import android.os.SystemClock
import java.io.File
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

enum class InferenceMode(val key: String, val title: String) {
    DEVICE("device", "本地识别"), CLOUD("cloud", "云端识别")
}

sealed interface ModelState {
    data object Loading : ModelState
    data class Ready(val info: ModelRepository.ModelInfo) : ModelState
    data class Error(val message: String) : ModelState
}

data class CaptureResult(
    val recordId: String,
    val photoPreview: ImageBitmap?,
    val prediction: Prediction,
    val displayName: String,
    val lowConfidence: Boolean,
    val source: InferenceMode = InferenceMode.DEVICE,
    val elapsedMs: Long = prediction.totalMs,
    val correctedDisplayName: String? = null,
)

data class CaptureUiState(
    val modelState: ModelState = ModelState.Loading,
    val capturing: Boolean = false,
    val lastResult: CaptureResult? = null,
    val showCorrectionSheet: Boolean = false,
    val message: String? = null,
    val mode: InferenceMode = InferenceMode.DEVICE,
    val failedPhoto: Boolean = false,
    val failure: String? = null,
)

/**
 * 采集页状态：模型加载、拍照识别、结果展示与人工纠错。
 * 推理在 viewModelScope 后台线程执行，不阻塞相机预览。
 */
class CaptureViewModel : ViewModel() {

    private val _state = MutableStateFlow(CaptureUiState())
    val state: StateFlow<CaptureUiState> = _state.asStateFlow()
    private var recognitionJob: Job? = null
    private var pendingPhoto: File? = null
    private var cloudPrepared = false
    private var capturedAt = 0L

    init {
        loadModel()
    }

    fun loadModel() {
        _state.update { it.copy(modelState = ModelState.Loading) }
        viewModelScope.launch {
            try {
                val info = AppGraph.modelRepository.info()
                _state.update { it.copy(modelState = ModelState.Ready(info)) }
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) { _state.update { it.copy(modelState = ModelState.Error(e.message ?: "模型加载失败")) } }
        }
    }

    /** 拍照保存回调：解码直立图 → 端侧推理 → 写入 Room → 触发上报（F02/F03/F04） */
    fun selectMode(mode: InferenceMode) { if (!_state.value.capturing) _state.update { it.copy(mode = mode) } }

    fun onCaptureStarted() { capturedAt = System.currentTimeMillis(); _state.update { it.copy(capturing = true) } }

    fun onPhotoSaved(file: File) {
        if (recognitionJob?.isActive == true) { file.delete(); return }
        replacePending(file)
        startRecognition()
    }

    private fun replacePending(file: File) {
        pendingPhoto?.takeIf { it != file }?.delete()
        pendingPhoto = file
        cloudPrepared = false
        _state.update { it.copy(failedPhoto = false, failure = null) }
    }

    fun retryPhoto(useLocal: Boolean = false) {
        if (_state.value.capturing || pendingPhoto == null) return
        if (useLocal) selectMode(InferenceMode.DEVICE)
        startRecognition()
    }

    private fun startRecognition() {
        val file = pendingPhoto ?: return
        val mode = _state.value.mode
        _state.update { it.copy(capturing = true, failedPhoto = false, failure = null) }
        recognitionJob = viewModelScope.launch { recognizeAndRecord(file, mode) }
    }

    /**
     * 导入图片识别：把所选图片复制进私有目录后走与拍照完全相同的识别链路
     * （EXIF 方向 → letterbox 预处理 → 推理 → Room 记录 → 触发上报）。
     * 使用系统图片选择器，不需要存储权限。
     */
    fun onPhotoImport(uri: android.net.Uri) {
        if (_state.value.capturing) return
        _state.update { it.copy(capturing = true) }
        capturedAt = System.currentTimeMillis()
        recognitionJob = viewModelScope.launch {
            val file = try {
                withContext(Dispatchers.IO) { AppGraph.photoStore.importToPrivateStorage(uri) }
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) {
                _state.update {
                    it.copy(
                        capturing = false,
                        message = "导入图片失败：${e.message ?: e.javaClass.simpleName}",
                    )
                }
                return@launch
            }
            replacePending(file)
            recognizeAndRecord(file, _state.value.mode)
        }
    }

    /** 拍照与导入共用的识别链路；调用前 [CaptureUiState.capturing] 必须已置位 */
    private suspend fun recognizeAndRecord(original: File, mode: InferenceMode) {
        var bitmap: android.graphics.Bitmap? = null
        val started = SystemClock.elapsedRealtime()
        try {
            val file = if (mode == InferenceMode.CLOUD && !cloudPrepared) {
                withContext(Dispatchers.IO) { AppGraph.photoStore.prepareCloudCopy(original) }.also {
                    pendingPhoto = it
                    cloudPrepared = true
                    original.delete()
                }
            } else original
            // JPEG 解码与 EXIF 旋转是文件 IO + 同步计算，放 IO 线程；classify 内部自行切 Default
            bitmap = withContext(Dispatchers.IO) {
                AppGraph.photoStore.decodeUpright(file)
            } ?: throw IllegalStateException("照片解码失败，不产生识别结果")
            var threshold = when (val ms = _state.value.modelState) {
                is ModelState.Ready -> ms.info.lowConfidenceThreshold
                else -> com.mobilecloud.recognition.inference.ModelBundle.DEFAULT_THRESHOLD
            }
            val prediction = if (mode == InferenceMode.DEVICE) AppGraph.modelRepository.classify(requireNotNull(bitmap)) else {
                AppGraph.apiClient.updateConfig(AppGraph.settings.currentConfig())
                val contract = withContext(Dispatchers.IO) {
                    val assets = AppGraph.appContext.assets
                    val metadata = ModelMetadata.parse(assets.open("models/metadata.json").bufferedReader().use { it.readText() })
                    val labelsText = assets.open("models/labels.txt").bufferedReader().use { it.readText() }
                    require(ShaUtil.sha256Hex(labelsText.toByteArray(Charsets.UTF_8)) == metadata.labelsSha256) { "标签哈希校验失败" }
                    val labels = labelsText.lineSequence().map { it.trim() }.filter { it.isNotEmpty() }.toList()
                    require(labels == AppGraph.categoryCatalog.categories.map { it.labelKey }) { "类别顺序不一致" }
                    CloudModelContract(requireNotNull(metadata.modelVersion), requireNotNull(metadata.sha256), labels,
                        metadata.lowConfidenceThreshold ?: .5f)
                }
                threshold = contract.threshold
                CloudClassifier(AppGraph.apiClient.api).classify(file, contract)
            }
            val elapsed = SystemClock.elapsedRealtime() - started
            val clientId = AppGraph.settings.ensureClientId()
            val now = System.currentTimeMillis()
            val record = RecordEntity(
                recordId = java.util.UUID.randomUUID().toString(),
                clientId = clientId,
                modelVersion = prediction.modelVersion,
                inferenceSource = mode.key,
                predictedIndex = prediction.index,
                predictedLabel = prediction.label,
                confidence = prediction.confidence,
                latencyMs = prediction.totalMs,
                capturedAt = capturedAt.takeIf { it > 0 } ?: now,
                photoPath = file.absolutePath,
                updatedAt = now,
            )
            val preview = bitmap.asImageBitmap()
            AppGraph.recordDao.insert(record)
            pendingPhoto = null
            _state.update { current ->
                current.copy(
                    capturing = false,
                    lastResult = CaptureResult(
                        recordId = record.recordId,
                        photoPreview = preview,
                        prediction = prediction,
                        displayName = AppGraph.categoryCatalog.displayNameForLabel(prediction.label),
                        lowConfidence = prediction.isLowConfidence(threshold),
                        source = mode,
                        elapsedMs = elapsed,
                    ),
                )
            }
            bitmap = null // Ownership transfers to the Compose result.
            runCatching { AppGraph.syncScheduler.requestSync() }.onFailure {
                _state.update { it.copy(message = "识别已保存，可到记录页手动同步") }
            }
        } catch (e: CancellationException) { throw e }
        catch (e: Exception) {
            _state.update { current ->
                current.copy(
                    capturing = false,
                    failedPhoto = true,
                    failure = "识别失败：${e.message ?: e.javaClass.simpleName}",
                )
            }
        } finally { bitmap?.recycle() }
    }

    fun onCaptureError(message: String) {
        _state.update { it.copy(capturing = false, message = "拍照失败：$message") }
    }

    fun startCorrection() {
        _state.update { it.copy(showCorrectionSheet = true) }
    }

    fun dismissCorrection() {
        _state.update { it.copy(showCorrectionSheet = false) }
    }

    /** 人工纠错：本地先落库（revision+1、保留原预测），再触发同步（F03/T10） */
    fun applyCorrection(categoryId: Int, displayName: String) {
        val result = _state.value.lastResult ?: return
        val now = System.currentTimeMillis()
        viewModelScope.launch {
            AppGraph.recordDao.applyCorrection(
                recordId = result.recordId,
                correctedIndex = categoryId,
                correctedLabel = AppGraph.categoryCatalog.categories
                    .firstOrNull { it.id == categoryId }?.labelKey ?: displayName,
                correctedAt = now,
                now = now,
            )
            AppGraph.syncScheduler.requestSync()
            _state.update { current ->
                current.copy(
                    showCorrectionSheet = false,
                    lastResult = current.lastResult?.let {
                        if (it.recordId == result.recordId) it.copy(correctedDisplayName = displayName) else it
                    },
                    message = "已记录修正（原预测保留，待同步）",
                )
            }
        }
    }

    fun consumeMessage() {
        _state.update { it.copy(message = null) }
    }
}
