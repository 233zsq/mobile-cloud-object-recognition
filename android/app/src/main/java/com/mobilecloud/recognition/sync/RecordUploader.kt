package com.mobilecloud.recognition.sync

import com.mobilecloud.recognition.data.local.RecordDao
import com.mobilecloud.recognition.data.remote.ApiService
import java.io.IOException

/**
 * 同步执行器：上传待传记录 + 同步纠错修订。
 * 幂等性依赖两点：同一记录永远使用同一 UUID；服务端对相同 UUID+内容返回已有记录（T07/T08）。
 * 任何失败只标记 lastError，不删除、不丢弃记录；下次触发继续补传。
 */
class RecordUploader(
    private val dao: RecordDao,
    private val api: ApiService,
    private val clock: () -> Long = System::currentTimeMillis,
) {

    data class Summary(
        val uploaded: Int,
        val correctionsSynced: Int,
        val failed: Int,
        val lastError: String?,
    ) {
        val success: Boolean get() = failed == 0
    }

    suspend fun syncAll(): Summary {
        var uploaded = 0
        var corrections = 0
        var failed = 0
        var lastError: String? = null

        for (record in dao.pendingUploads()) {
            try {
                val response = api.uploadRecord(RecordMapper.toUploadRequest(record))
                if (response.isSuccessful) {
                    dao.markUploaded(record.recordId, clock())
                    uploaded++
                } else {
                    val message = RecordMapper.uploadErrorMessage(response.code())
                    dao.markError(record.recordId, message, clock())
                    failed++
                    lastError = message
                }
            } catch (e: IOException) {
                val message = "网络不可用：${e.message ?: "连接失败"}"
                dao.markError(record.recordId, message, clock())
                failed++
                lastError = message
            } catch (e: Exception) {
                val message = "上报异常：${e.message ?: e.javaClass.simpleName}"
                dao.markError(record.recordId, message, clock())
                failed++
                lastError = message
            }
        }

        for (record in dao.pendingCorrections()) {
            try {
                val response = api.correctLabel(record.recordId, RecordMapper.toCorrectionRequest(record))
                if (response.isSuccessful) {
                    // 传入发送时的修订号：若等待期间用户又纠错（revision 已递增），
                    // 此处不会清除新修订的待同步标志
                    dao.markCorrectionSynced(record.recordId, record.revision, clock())
                    corrections++
                } else {
                    val message = correctionErrorMessage(response.code())
                    dao.markError(record.recordId, message, clock())
                    failed++
                    lastError = message
                }
            } catch (e: IOException) {
                val message = "网络不可用：${e.message ?: "连接失败"}"
                dao.markError(record.recordId, message, clock())
                failed++
                lastError = message
            } catch (e: Exception) {
                val message = "纠错同步异常：${e.message ?: e.javaClass.simpleName}"
                dao.markError(record.recordId, message, clock())
                failed++
                lastError = message
            }
        }

        return Summary(uploaded, corrections, failed, lastError)
    }

    companion object {
        fun correctionErrorMessage(httpCode: Int): String = when (httpCode) {
            409, 422 -> "纠错修订被拒绝（HTTP $httpCode）：服务端已有更新的修订号，旧请求不能覆盖"
            400 -> "纠错被拒：字段校验未通过（HTTP 400）"
            404 -> "纠错失败：记录在服务端不存在（HTTP 404）"
            in 500..599 -> "服务端错误（HTTP $httpCode），稍后自动重试"
            else -> "纠错同步失败（HTTP $httpCode）"
        }
    }
}
