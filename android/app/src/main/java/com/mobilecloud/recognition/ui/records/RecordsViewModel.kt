package com.mobilecloud.recognition.ui.records

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.mobilecloud.recognition.AppGraph
import com.mobilecloud.recognition.data.local.RecordEntity
import java.io.File
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class RecordsUiState(
    val records: List<RecordEntity> = emptyList(),
    val total: Int = 0,
    val pendingCount: Int = 0,
    val syncing: Boolean = false,
    val message: String? = null,
)

/**
 * 记录页状态：本地记录列表（含同步状态与纠错信息）+ 手动同步。
 * 列表来自 Room Flow，上传成功后自动刷新。
 */
class RecordsViewModel : ViewModel() {

    private val syncing = MutableStateFlow(false)
    private val message = MutableStateFlow<String?>(null)

    val state: StateFlow<RecordsUiState> = combine(
        AppGraph.recordDao.observeAll(),
        AppGraph.recordDao.observeTotal(),
        AppGraph.recordDao.observePendingCount(),
        syncing,
        message,
    ) { records, total, pending, isSyncing, currentMessage ->
        RecordsUiState(records, total, pending, isSyncing, currentMessage)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), RecordsUiState())

    /** 手动立即同步：直接调用上传器以获得即时反馈；后台 Worker 补传仍由调度器负责（F04/T07） */
    fun syncNow() {
        if (syncing.value) return
        viewModelScope.launch {
            syncing.value = true
            val summary = AppGraph.uploader.syncAll()
            message.value = if (summary.success) {
                "同步完成：新上传 ${summary.uploaded} 条，纠错同步 ${summary.correctionsSynced} 条"
            } else {
                "同步未全部完成（${summary.failed} 条失败）：${summary.lastError ?: "网络不可用"}"
            }
            syncing.value = false
        }
    }

    /**
     * 删除单条记录（本地）：先删数据库行，再删除对应照片文件。
     * 云端已入库的数据不受影响（后端无删除接口），确认框文案见 [RecordDeletionText]。
     */
    fun deleteRecord(record: RecordEntity) {
        viewModelScope.launch {
            AppGraph.recordDao.delete(record.recordId)
            val photoPath = record.photoPath
            if (!photoPath.isNullOrBlank()) {
                withContext(Dispatchers.IO) {
                    runCatching { File(photoPath).delete() }
                }
            }
            message.value = RecordDeletionText.result(record.uploaded)
        }
    }

    fun consumeMessage() {
        message.value = null
    }
}
