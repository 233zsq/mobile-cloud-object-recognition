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
 * App 设置：服务器地址、访问令牌、客户端标识。
 * baseURL 可配置以适配联调环境；client_id 首次启动生成并固定，用于服务端区分客户端。
 */
class SettingsStore(private val context: Context) {

    val baseUrlFlow: Flow<String> = context.dataStore.data.map { it[KEY_BASE_URL] ?: DEFAULT_BASE_URL }
    val tokenFlow: Flow<String> = context.dataStore.data.map { it[KEY_TOKEN] ?: "" }
    val clientIdFlow: Flow<String> = context.dataStore.data.map { it[KEY_CLIENT_ID] ?: "" }

    suspend fun currentBaseUrl(): String = baseUrlFlow.first()
    suspend fun currentToken(): String = tokenFlow.first()

    /** 返回已存在的 client_id，不存在则生成并持久化 */
    suspend fun ensureClientId(): String {
        context.dataStore.data.first()[KEY_CLIENT_ID]?.let { return it }
        val id = UUID.randomUUID().toString()
        context.dataStore.edit { it[KEY_CLIENT_ID] = id }
        return id
    }

    suspend fun setBaseUrl(value: String) {
        context.dataStore.edit { it[KEY_BASE_URL] = value.trim() }
    }

    suspend fun setToken(value: String) {
        context.dataStore.edit { it[KEY_TOKEN] = value.trim() }
    }

    companion object {
        /** 与仓库根 .env.example 的 API_BASE_URL 保持一致 */
        const val DEFAULT_BASE_URL = "http://localhost:8080"

        private val KEY_BASE_URL = stringPreferencesKey("base_url")
        private val KEY_TOKEN = stringPreferencesKey("api_token")
        private val KEY_CLIENT_ID = stringPreferencesKey("client_id")
    }
}
