package com.mobilecloud.recognition.data.remote

import java.net.URI

/**
 * 服务器地址解析与校验（纯函数，便于单测）。
 * 设置页保存前先校验，避免把无效地址写入持久化配置；
 * 网络层用它重写请求 URL。
 */
object BaseUrl {

    data class Parsed(val scheme: String, val host: String, val port: Int)

    fun parse(raw: String?): Parsed? {
        val value = raw?.trim() ?: return null
        if (value.isEmpty()) return null
        val uri = runCatching { URI(value) }.getOrNull() ?: return null
        val scheme = uri.scheme?.lowercase()?.takeIf { it == "http" || it == "https" } ?: return null
        val host = uri.host?.takeIf { it.isNotBlank() } ?: return null
        val port = if (uri.port > 0) uri.port else if (scheme == "https") 443 else 80
        return Parsed(scheme, host, port)
    }

    fun isValid(raw: String?): Boolean = parse(raw) != null
}