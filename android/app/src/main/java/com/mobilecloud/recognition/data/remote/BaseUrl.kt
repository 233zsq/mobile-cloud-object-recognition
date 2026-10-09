package com.mobilecloud.recognition.data.remote

import java.net.URI

/**
 * 服务器地址解析与校验（纯函数，便于单测）。
 * 设置页保存前先校验，避免把无效地址写入持久化配置；
 * 网络层用它重写请求 URL。
 */
object BaseUrl {

    /** 显式端口必须落在 TCP 合法范围（PR 审查修复项：>65535 会被接受并覆盖有效配置） */
    private val VALID_PORTS = 1..65535

    data class Parsed(val scheme: String, val host: String, val port: Int)

    fun parse(raw: String?): Parsed? {
        val value = raw?.trim() ?: return null
        if (value.isEmpty()) return null
        val uri = runCatching { URI(value) }.getOrNull() ?: return null
        val scheme = uri.scheme?.lowercase()?.takeIf { it == "http" || it == "https" } ?: return null
        val host = uri.host?.takeIf { it.isNotBlank() } ?: return null
        val explicitPort = uri.port
        if (explicitPort != -1 && explicitPort !in VALID_PORTS) return null
        val port = if (explicitPort > 0) explicitPort else if (scheme == "https") 443 else 80
        return Parsed(scheme, host, port)
    }

    fun isValid(raw: String?): Boolean = parse(raw) != null
}