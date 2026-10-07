package com.mobilecloud.recognition.ui.capture

import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.mobilecloud.recognition.AppGraph
import com.mobilecloud.recognition.data.local.RecordEntity
import com.mobilecloud.recognition.inference.ModelRepository
import com.mobilecloud.recognition.inference.Prediction
import java.io.File
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

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
    val correctedDisplayName: String? = null,
)

data class CaptureUiState(
    val modelState: ModelState = ModelState.Loading,
    val capturing: Boolean = false,
    val lastResult: CaptureResult? = null,
    val showCorrectionSheet: Boolean = false,
    val message: String? = null,
)

/**
 * 采集页状态：模型加载、拍照识别、结果展示与人工纠错。
 * 推理在 viewModelScope 后台线程执行，不阻塞相机预览。
 */
class CaptureViewModel : ViewModel() {

    private val _state = MutableStateFlow(CaptureUiState())
    val state: StateFlow<CaptureUiState> = _state.asStateFlow()

    init {
        loadModel()
    }

    fun loadModel() {
        _state.update { it.copy(modelState = ModelState.Loading) }
        viewModelScope.launch {
            _state.update { current ->
                try {
                    current.copy(modelState = ModelState.Ready(AppGraph.modelRepository.info()))
                } catch (e: Exception) {
                    current.copy(
                        modelState = ModelState.Error(e.message ?: "模型加载失败"),
                        message = "模型不可用：${e.message}",
                    )
                }
            }
        }
    }

    /** 拍照保存回调：解码直立图 → 端侧推理 → 写入 Room → 触发上报（F02/F03/F04） */
    fun onPhotoSaved(file: File) {
        if (_state.value.capturing) return
        _state.update { it.copy(capturing = true) }
        viewModelScope.launch {
            try {
                val bitmap = AppGraph.photoStore.decodeUpright(file)
                    ?: throw IllegalStateException("照片解码失败，不产生识别结果")
                val prediction = AppGraph.modelRepository.classify(bitmap)
                val clientId = AppGraph.settings.ensureClientId()
                val now = System.currentTimeMillis()
                val record = RecordEntity(
                    recordId = java.util.UUID.randomUUID().toString(),
                    clientId = clientId,
                    modelVersion = prediction.modelVersion,
                    predictedIndex = prediction.index,
                    predictedLabel = prediction.label,
                    confidence = prediction.confidence,
                    latencyMs = prediction.totalMs,
                    capturedAt = now,
                    photoPath = file.absolutePath,
                    updatedAt = now,
                )
                AppGraph.recordDao.insert(record)
                AppGraph.syncScheduler.requestSync()

                val threshold = when (val ms = _state.value.modelState) {
                    is ModelState.Ready -> ms.info.lowConfidenceThreshold
                    else -> com.mobilecloud.recognition.inference.ModelBundle.DEFAULT_THRESHOLD
                }
                _state.update { current ->
                    current.copy(
                        capturing = false,
                        lastResult = CaptureResult(
                            recordId = record.recordId,
                            photoPreview = bitmap.asImageBitmap(),
                            prediction = prediction,
                            displayName = AppGraph.categoryCatalog.displayNameForLabel(prediction.label),
                            lowConfidence = prediction.isLowConfidence(threshold),
                        ),
                    )
                }
            } catch (e: Exception) {
                _state.update { current ->
                    current.copy(
                        capturing = false,
                        message = "识别失败：${e.message ?: e.javaClass.simpleName}",
                    )
                }
            }
        }
    }

    fun onCaptureError(message: String) {
        _state.update { it.copy(message = "拍照失败：$message") }
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
                    lastResult = current.lastResult?.copy(correctedDisplayName = displayName),
                    message = "已记录修正（原预测保留，待同步）",
                )
            }
        }
    }

    fun consumeMessage() {
        _state.update { it.copy(message = null) }
    }
}
