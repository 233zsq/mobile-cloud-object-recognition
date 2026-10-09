package com.mobilecloud.recognition.data.remote

import com.mobilecloud.recognition.data.settings.ServerConfig
import com.mobilecloud.recognition.data.settings.SettingsStore

/**
 * 请求目标重写（纯函数，便于单测）。
 * 每次请求只接受一次配置快照 [ServerConfig]，地址与令牌必然来自同一份快照。
 */
object RequestRewriter {

    data class Plan(
        val scheme: String?,
        val host: String?,
        val port: Int?,
        val token: String?,
    )

    fun plan(requestUrl: String, config: ServerConfig): Plan {
        // 占位默认地址视为"未配置"：不重写、不带令牌，请求快速失败
        val parsed = if (config.baseUrl.trim() == SettingsStore.DEFAULT_BASE_URL) {
            null
        } else {
            BaseUrl.parse(config.baseUrl)
        }
        return Plan(
            scheme = parsed?.scheme,
            host = parsed?.host,
            port = parsed?.port,
            token = config.token.trim().takeIf { it.isNotEmpty() },
        )
    }
}