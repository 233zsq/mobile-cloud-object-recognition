package com.mobilecloud.recognition.ui.capture

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.mobilecloud.recognition.AppGraph
import com.mobilecloud.recognition.data.local.RecordEntity
import com.mobilecloud.recognition.inference.ModelRepository
import com.mobilecloud.recognition.inference.Prediction
import com.mobilecloud.recognition.inference.CloudClassifier
import com.mobilecloud.recognition.inference.validated
import com.mobilecloud.recognition.inference.contract
import com.mobilecloud.recognition.data.remote.CloudModelOption
import com.mobilecloud.recognition.data.settings.ServerConfig
import android.os.SystemClock
import androidx.camera.core.ImageProxy
import com.mobilecloud.recognition.camera.PreviewFrameBitmap
import com.mobilecloud.recognition.inference.LiveObservation
import com.mobilecloud.recognition.inference.LiveRecognitionSession
import com.mobilecloud.recognition.inference.LiveResultTracker
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
    val prediction: Prediction,
    val displayName: String,
    val lowConfidence: Boolean,
    val source: InferenceMode = InferenceMode.DEVICE,
    val elapsedMs: Long = prediction.totalMs,
    val correctedDisplayName: String? = null,
    val manuallyConfirmed: Boolean = false,
)

data class PhotoConfirmation(val prediction: Prediction, val displayName: String, val elapsedMs: Long,
    val lowConfidenceThreshold: Float = com.mobilecloud.recognition.inference.ModelBundle.DEFAULT_THRESHOLD,
    val photoPath: String? = null)

data class CaptureUiState(
    val modelState: ModelState = ModelState.Loading,
    val capturing: Boolean = false,
    val lastResult: CaptureResult? = null,
    val showCorrectionSheet: Boolean = false,
    val message: String? = null,
    val mode: InferenceMode = InferenceMode.DEVICE,
    val failedPhoto: Boolean = false,
    val failure: String? = null,
    val cloudModels: List<CloudModelOption> = emptyList(),
    val cloudModelVersion: String? = null,
    val cloudModelsLoading: Boolean = false,
    val cloudModelsError: String? = null,
    val liveEnabled: Boolean = false,
    val liveActive: Boolean = false,
    val liveCameraReady: Boolean = false,
    val liveObservation: LiveObservation? = null,
    val liveError: String? = null,
    val confirmation: PhotoConfirmation? = null,
)

/**
 * 采集页状态：模型加载、拍照识别、结果展示与人工纠错。
 * 推理在 viewModelScope 后台线程执行，不阻塞相机预览。
 */
class CaptureViewModel(
    private val insertRecord: suspend (RecordEntity) -> Unit = { AppGraph.recordDao.insert(it) },
    private val requestRecordSync: () -> Unit = { AppGraph.syncScheduler.requestSync() },
) : ViewModel() {

    private val _state = MutableStateFlow(CaptureUiState())
    val state: StateFlow<CaptureUiState> = _state.asStateFlow()
    private var recognitionJob: Job? = null
    private var pendingPhoto: File? = null
    private var cloudPrepared = false
    private var capturedAt = 0L
    private var modelsJob: Job? = null
    private var catalogConfig: ServerConfig? = null
    private val liveSession = LiveRecognitionSession()
    private val liveTracker = LiveResultTracker()

    init {
        loadModel()
    }

    fun loadModel() {
        setLivePreviewActive(false)
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
    fun selectMode(mode: InferenceMode) {
        if (_state.value.capturing || _state.value.confirmation != null) return
        if (mode != _state.value.mode) setLivePreviewActive(false)
        _state.update { it.copy(mode = mode) }
        if (mode == InferenceMode.CLOUD) refreshCloudModels()
    }

    fun refreshCloudModels() {
        if (_state.value.capturing || modelsJob?.isActive == true) return
        _state.update { it.copy(cloudModelsLoading = true, cloudModelsError = null) }
        modelsJob = viewModelScope.launch {
            try {
                val config = AppGraph.settings.currentConfig()
                AppGraph.apiClient.updateConfig(config)
                val catalog = AppGraph.apiClient.api.models().validated(AppGraph.categoryCatalog.categories.map { it.labelKey })
                require(AppGraph.settings.currentConfig() == config) { "连接设置已变化，请重新加载模型" }
                val saved = _state.value.cloudModelVersion ?: AppGraph.settings.cloudModelVersion()
                val selected = saved ?: catalog.defaultModelVersion
                catalogConfig = config
                _state.update { it.copy(cloudModels = catalog.models, cloudModelVersion = selected,
                    cloudModelsLoading = false, cloudModelsError = if (catalog.models.none { m -> m.version == selected && m.available })
                        "上次选择的模型不可用，请选择一个就绪模型。" else null) }
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) {
                _state.update { it.copy(cloudModelsLoading = false, cloudModels = emptyList(),
                    cloudModelsError = "无法读取云端模型，请检查已保存的连接与口令后重试。") }
            }
        }
    }

    fun selectCloudModel(version: String) {
        if (_state.value.capturing || _state.value.cloudModels.none { it.version == version && it.available }) return
        _state.update { it.copy(cloudModelVersion = version, cloudModelsError = null) }
        viewModelScope.launch {
            try { AppGraph.settings.setCloudModelVersion(version) }
            catch (e: CancellationException) { throw e }
            catch (e: Exception) { _state.update { it.copy(message = "本次模型选择已生效，但未能保存到设备。") } }
        }
    }

    fun onCaptureStarted() {
        setLivePreviewActive(false)
        capturedAt = System.currentTimeMillis()
        _state.update { it.copy(capturing = true) }
    }

    fun setLiveEnabled(enabled: Boolean) {
        if (_state.value.capturing || _state.value.mode != InferenceMode.DEVICE) return
        setLivePreviewActive(false)
        _state.update { it.copy(liveEnabled = enabled, liveError = null) }
    }

    fun setLiveCameraReady(ready: Boolean) {
        if (!ready) setLivePreviewActive(false)
        _state.update { it.copy(liveCameraReady = ready) }
    }

    fun onLiveCameraUnavailable() {
        setLivePreviewActive(false)
        _state.update { it.copy(liveEnabled = false, liveCameraReady = false,
            message = "此设备暂不支持实时观察，仍可拍照或选择图片识别。") }
    }

    /** Main-thread lifecycle changes invalidate results already being computed on the analyzer thread. */
    fun setLivePreviewActive(requested: Boolean) {
        val current = _state.value
        val active = requested && current.liveEnabled && current.liveCameraReady &&
            current.mode == InferenceMode.DEVICE && current.modelState is ModelState.Ready &&
            !current.capturing && current.confirmation == null
        if (liveSession.setActive(active)) {
            liveTracker.reset()
            _state.update { it.copy(liveActive = active, liveObservation = null, liveError = null) }
        }
    }

    /** Called on CameraX's single analyzer executor. No file, database or network access. */
    suspend fun analyzePreviewFrame(image: ImageProxy) {
        var bitmap: android.graphics.Bitmap? = null
        val ticket = liveSession.begin(SystemClock.elapsedRealtime())
        try {
            if (ticket == null || !liveSession.isCurrent(ticket)) return
            bitmap = PreviewFrameBitmap.upright(image)
            val prediction = AppGraph.modelRepository.tryClassifyPreview(bitmap)
            withContext(Dispatchers.Main.immediate) {
                val now = SystemClock.elapsedRealtime()
                if (liveSession.finish(ticket, now) && prediction != null) {
                    val threshold = (_state.value.modelState as? ModelState.Ready)?.info?.lowConfidenceThreshold
                        ?: return@withContext
                    val observation = liveTracker.observe(prediction, threshold, now)
                    _state.update { it.copy(liveObservation = observation, liveError = null) }
                }
            }
        } catch (e: CancellationException) { throw e }
        catch (e: Exception) {
            withContext(Dispatchers.Main.immediate) {
                if (ticket != null && liveSession.finish(ticket, SystemClock.elapsedRealtime())) {
                    liveTracker.reset()
                    _state.update { it.copy(liveObservation = null, liveError = "实时观察暂不可用，请关闭后重试。") }
                }
            }
        } finally {
            if (ticket != null) liveSession.finish(ticket, SystemClock.elapsedRealtime())
            bitmap?.recycle()
            image.close()
        }
    }

    fun expireLiveObservation() {
        val observation = _state.value.liveObservation ?: return
        if (SystemClock.elapsedRealtime() - observation.observedAt > LiveResultTracker.FRESHNESS_MS) {
            liveTracker.reset()
            _state.update { it.copy(liveObservation = null) }
        }
    }

    override fun onCleared() {
        liveSession.setActive(false)
        super.onCleared()
    }

    fun onPhotoSaved(file: File) {
        if (recognitionJob?.isActive == true || _state.value.confirmation != null) { file.delete(); return }
        replacePending(file)
        startRecognition()
    }

    private fun replacePending(file: File) {
        pendingPhoto?.takeIf { it != file }?.delete()
        pendingPhoto = file
        cloudPrepared = false
        _state.update { it.copy(failedPhoto = false, failure = null, confirmation = null) }
    }

    fun retryPhoto(useLocal: Boolean = false) {
        if (_state.value.capturing || pendingPhoto == null) return
        if (useLocal) selectMode(InferenceMode.DEVICE)
        startRecognition()
    }

    private fun startRecognition() {
        val file = pendingPhoto ?: return
        setLivePreviewActive(false)
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
        if (_state.value.capturing || _state.value.confirmation != null) return
        setLivePreviewActive(false)
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
                val selected = _state.value.cloudModelVersion ?: error("请先选择云端模型")
                val previous = _state.value.cloudModels.singleOrNull { it.version == selected }
                    ?: error("请先刷新云端模型列表")
                val config = AppGraph.settings.currentConfig()
                require(config == catalogConfig) { "连接设置已变化，请刷新云端模型后重试" }
                AppGraph.apiClient.updateConfig(config)
                val catalog = AppGraph.apiClient.api.models().validated(AppGraph.categoryCatalog.categories.map { it.labelKey })
                val fresh = catalog.models.singleOrNull { it.version == selected && it.available }
                    ?: error("所选模型暂不可用，请刷新列表后手动选择")
                require(fresh.sha256 == previous.sha256 && fresh.labelsSha256 == previous.labelsSha256
                    && fresh.categoryVersion == previous.categoryVersion && fresh.threshold == previous.threshold) {
                    "所选模型规格已变化，请刷新列表后手动选择"
                }
                val contract = fresh.contract()
                threshold = contract.threshold
                CloudClassifier(AppGraph.apiClient.api).classify(file, contract)
            }
            val elapsed = SystemClock.elapsedRealtime() - started
            if (mode == InferenceMode.DEVICE && prediction.scopeDecision?.needsConfirmation == true) {
                _state.update { it.copy(capturing = false, failedPhoto = false, failure = null,
                    confirmation = PhotoConfirmation(prediction,
                        AppGraph.categoryCatalog.displayNameForLabel(prediction.label), elapsed, threshold, file.absolutePath)) }
                return
            }
            savePrediction(file, prediction, threshold, mode, elapsed)
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

    private suspend fun savePrediction(file: File, prediction: Prediction, threshold: Float, mode: InferenceMode,
        elapsed: Long, confirmedCategory: Int? = null) {
            val clientId = AppGraph.settings.ensureClientId()
            val now = System.currentTimeMillis()
            val corrected = confirmedCategory?.takeIf { it != prediction.index }
            val correctedLabel = corrected?.let { id -> AppGraph.categoryCatalog.categories.single { it.id == id }.labelKey }
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
                correctedIndex = corrected,
                correctedLabel = correctedLabel,
                revision = if (corrected != null) 1 else 0,
                correctedAt = if (corrected != null) now else null,
                correctionPending = corrected != null,
                updatedAt = now,
            )
            insertRecord(record)
            pendingPhoto = null
            _state.update { current ->
                current.copy(
                    capturing = false,
                    confirmation = null,
                    lastResult = CaptureResult(
                        recordId = record.recordId,
                        prediction = prediction,
                        displayName = AppGraph.categoryCatalog.displayNameForLabel(prediction.label),
                        lowConfidence = prediction.isLowConfidence(threshold),
                        source = mode,
                        elapsedMs = elapsed,
                        correctedDisplayName = correctedLabel?.let(AppGraph.categoryCatalog::displayNameForLabel),
                        manuallyConfirmed = confirmedCategory != null,
                    ),
                )
            }
            runCatching { requestRecordSync() }.onFailure {
                _state.update { it.copy(message = "识别已保存，可到记录页手动同步") }
            }
    }

    fun confirmPhoto(categoryId: Int) {
        val candidate = _state.value.confirmation ?: return
        val file = pendingPhoto ?: return
        if (_state.value.capturing || AppGraph.categoryCatalog.categories.none { it.id == categoryId }) return
        setLivePreviewActive(false)
        _state.update { it.copy(capturing = true) }
        recognitionJob = viewModelScope.launch {
            try { savePrediction(file, candidate.prediction, candidate.lowConfidenceThreshold,
                InferenceMode.DEVICE, candidate.elapsedMs, categoryId) }
            catch (e: CancellationException) { throw e }
            catch (_: Exception) { _state.update { it.copy(capturing = false, message = "记录保存失败，照片已保留，请重试。") } }
        }
    }

    fun discardConfirmation() {
        if (_state.value.capturing || _state.value.confirmation == null) return
        pendingPhoto?.delete()
        pendingPhoto = null
        cloudPrepared = false
        _state.update { it.copy(confirmation = null, lastResult = null) }
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
