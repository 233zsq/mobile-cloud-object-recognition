package com.mobilecloud.recognition.data.remote

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/**
 * 服务端统一错误结构（backend/app/errors.py）：
 * `{"error":{"code":"...","message":"..."},"request_id":"UUID"}`
 */
@Serializable
data class ServerErrorEnvelope(
    val error: ServerErrorBody? = null,
    @SerialName("request_id") val requestId: String? = null,
)

@Serializable
data class ServerErrorBody(
    val code: String = "",
    val message: String = "",
)

/**
 * 把 HTTP 响应体解析成可读失败说明（纯函数，便于单测）。
 * 只按状态码映射会把「模型版本未登记」误报成「字段校验未通过」，
 * 联调时必须以服务端错误码为准（PR 联调修复项）。
 */
object ServerErrorParser {

    private val json = Json { ignoreUnknownKeys = true }

    fun parse(body: String?): ServerErrorBody? {
        if (body.isNullOrBlank()) return null
        return runCatching { json.decodeFromString<ServerErrorEnvelope>(body) }
            .getOrNull()
            ?.error
            ?.takeIf { it.code.isNotBlank() || it.message.isNotBlank() }
    }

    /** 服务端错误码对应的排查提示 */
    fun hint(code: String): String? = when (code) {
        "UNKNOWN_MODEL_VERSION" -> "该模型版本未在服务端登记，需数据与云端负责人执行 register-model"
        "UNKNOWN_CATEGORY" -> "预测类别不属于该模型的类别版本"
        "INVALID_RECORD" -> "原始字段校验未通过"
        "RECORD_CONFLICT" -> "同 UUID 不同内容，服务端拒绝覆盖"
        "DATABASE_UNAVAILABLE" -> "服务端数据库不可用，稍后重试"
        else -> null
    }

    /** 组装展示文案；无结构化错误体时回退到状态码说明 */
    fun describe(statusCode: Int, body: String?, fallback: String): String {
        val parsed = parse(body) ?: return fallback
        val message = parsed.message.ifBlank { parsed.code }
        val codePart = parsed.code.takeIf { it.isNotBlank() }?.let { "（$it，HTTP $statusCode）" }
            ?: "（HTTP $statusCode）"
        val hintPart = hint(parsed.code)?.let { "；$it" } ?: ""
        return "服务端拒绝：$message$codePart$hintPart"
    }
}