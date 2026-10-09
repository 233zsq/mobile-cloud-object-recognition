package com.mobilecloud.recognition.data.settings

/**
 * 服务器地址与访问令牌的不可变快照。
 * 读取、持久化与请求层更新都以整个对象为单位，避免并发切换时出现
 * 「A 的地址 + B 的令牌」这类交叉组合（PR 审查修复项）。
 */
data class ServerConfig(val baseUrl: String, val token: String) {
    companion object {
        val DEFAULT = ServerConfig(SettingsStore.DEFAULT_BASE_URL, "")
    }
}