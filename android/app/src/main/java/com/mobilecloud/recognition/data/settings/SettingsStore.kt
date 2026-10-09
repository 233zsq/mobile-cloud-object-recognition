package com.mobilecloud.recognition.data.settings

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import java.util.UUID

private val Context.dataStore by preferencesDataStore(name = "settings")

/**
 * App 设置：服务器地址与访问令牌作为单个 [ServerConfig] 快照读写（原子），
 * client_id 首次启动生成并固定，用于服务端区分客户端。
 */
class SettingsStore(private val context: Context) {

    val configFlow: Flow<ServerConfig> = context.dataStore.data.map { prefs ->
        ServerConfig(
            baseUrl = prefs[KEY_BASE_URL] ?: DEFAULT_BASE_URL,
            token = prefs[KEY_TOKEN] ?: "",
        )
    }

    val clientIdFlow: Flow<String> = context.dataStore.data.map { it[KEY_CLIENT_ID] ?: "" }

    /** 单次读取整个配置快照：地址与令牌必然同源 */
    suspend fun currentConfig(): ServerConfig = configFlow.first()

    /** 单次事务写入地址与令牌，避免只写入一半 */
    suspend fun setConfig(config: ServerConfig) {
        context.dataStore.edit { prefs ->
            prefs[KEY_BASE_URL] = config.baseUrl.trim()
            prefs[KEY_TOKEN] = config.token.trim()
        }
    }

    /** 返回已存在的 client_id，不存在则生成并持久化 */
    suspend fun ensureClientId(): String {
        context.dataStore.data.first()[KEY_CLIENT_ID]?.let { return it }
        val id = UUID.randomUUID().toString()
        context.dataStore.edit { it[KEY_CLIENT_ID] = id }
        return id
    }

    companion object {
        /** 与仓库根 .env.example 的 API_BASE_URL 保持一致；表示"未配置"的占位值 */
        const val DEFAULT_BASE_URL = "http://localhost:8080"

        /** 组内腾讯云实例（deploy/README.md），证书信任见 res/xml/network_security_config.xml */
        const val TEAM_SERVER_URL = "https://49.232.195.47"

        private val KEY_BASE_URL = stringPreferencesKey("base_url")
        private val KEY_TOKEN = stringPreferencesKey("api_token")
        private val KEY_CLIENT_ID = stringPreferencesKey("client_id")
    }
}