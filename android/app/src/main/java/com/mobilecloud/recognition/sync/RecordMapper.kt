package com.mobilecloud.recognition.sync

import com.mobilecloud.recognition.data.local.RecordEntity
import com.mobilecloud.recognition.data.remote.CorrectionRequest
import com.mobilecloud.recognition.data.remote.RecordUploadRequest
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/** 实体与接口 DTO 的映射，纯函数便于单测。时间统一 ISO-8601 含时区（联调前需冻结项之一）。 */
object RecordMapper {

    private val isoFormatter: DateTimeFormatter =
        DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss.SSSXXX")

    fun isoTime(epochMillis: Long, zone: ZoneId = ZoneId.systemDefault()): String =
        isoFormatter.format(Instant.ofEpochMilli(epochMillis).atZone(zone))

    fun toUploadRequest(entity: RecordEntity): RecordUploadRequest = RecordUploadRequest(
        recordId = entity.recordId,
        clientId = entity.clientId,
        inferenceSource = SOURCE_DEVICE,
        modelVersion = entity.modelVersion,
        predictedId = entity.predictedIndex,
        confidence = entity.confidence,
        latencyMs = entity.latencyMs,
        capturedAt = isoTime(entity.capturedAt),
    )

    fun toCorrectionRequest(entity: RecordEntity): CorrectionRequest = CorrectionRequest(
        correctedId = entity.correctedIndex ?: -1,
        revision = entity.revision,
        correctedAt = isoTime(entity.correctedAt ?: entity.updatedAt),
    )

    /** 上报失败的用户可读说明 */
    fun uploadErrorMessage(httpCode: Int): String = when (httpCode) {
        409 -> "服务端已存在同UUID但内容不同的记录，拒绝覆盖（T09冲突）"
        400 -> "服务端拒绝：字段校验未通过（HTTP 400）"
        401, 403 -> "认证失败（HTTP $httpCode），检查设置页令牌"
        404 -> "接口不存在（HTTP 404），确认服务地址与版本"
        in 500..599 -> "服务端错误（HTTP $httpCode），稍后自动重试"
        else -> "上报失败（HTTP $httpCode）"
    }

    const val SOURCE_DEVICE = "device"
    const val SOURCE_CLOUD = "cloud"
}
