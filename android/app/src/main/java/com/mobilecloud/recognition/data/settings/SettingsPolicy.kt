package com.mobilecloud.recognition.data.settings

import com.mobilecloud.recognition.data.remote.BaseUrl

/**
 * 配置保存策略（纯函数，便于单测）。
 * 无效输入必须在写入持久化之前拒绝，避免覆盖掉仍然可用的配置（PR 审查修复项）。
 */
object SettingsPolicy {

    /** 返回 null 表示可以保存；否则返回面向用户的中文原因 */
    fun validateForSave(config: ServerConfig): String? {
        val url = config.baseUrl.trim()
        if (url == SettingsStore.DEFAULT_BASE_URL) return null
        if (url.isEmpty()) return "地址不能为空，未保存；此前配置保持不变"
        if (!BaseUrl.isValid(url)) {
            return "地址格式无效（需 http(s)://主机[:端口]，端口范围 1-65535），未保存；此前配置保持不变"
        }
        return null
    }
}