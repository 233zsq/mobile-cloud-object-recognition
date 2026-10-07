package com.mobilecloud.recognition.data.remote

import com.mobilecloud.recognition.data.settings.SettingsStore
import java.net.URI
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference
import kotlinx.serialization.json.Json
import okhttp3.HttpUrl
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Response
import retrofit2.Retrofit
import retrofit2.converter.kotlinx.serialization.asConverterFactory

/**
 * Retrofit 客户端。服务器地址与令牌可在设置页修改并即时生效（拦截器重写 URL），
 * 避免联调期间改地址要重装 App。
 */
class ApiClient(settings: SettingsStore) {

    private val baseUrlRef = AtomicReference(SettingsStore.DEFAULT_BASE_URL)
    private val tokenRef = AtomicReference("")

    /** 从设置的服务器地址解析出 scheme/host/port，非法则返回 null（保留默认地址快速报错） */
    private fun parseBaseUrl(): Triple<String, String, Int>? {
        val base = baseUrlRef.get()
        if (base == SettingsStore.DEFAULT_BASE_URL) return null
        val uri = runCatching { URI(base.trim()) }.getOrNull() ?: return null
        val scheme = uri.scheme?.lowercase() ?: return null
        if (scheme != "http" && scheme != "https") return null
        val host = uri.host ?: return null
        val port = if (uri.port > 0) uri.port else if (scheme == "https") 443 else 80
        return Triple(scheme, host, port)
    }

    private val dynamicConfigInterceptor = Interceptor { chain ->
        val original = chain.request()
        val rewrittenUrl: HttpUrl = original.url.newBuilder().apply {
            val config = parseBaseUrl()
            if (config != null) {
                scheme(config.first)
                host(config.second)
                port(config.third)
            }
        }.build()
        val request = original.newBuilder().url(rewrittenUrl).let { builder ->
            val token = tokenRef.get()
            if (token.isNotBlank()) builder.header("Authorization", "Bearer $token") else builder
        }.build()
        chain.proceed(request)
    }

    val json: Json = Json {
        ignoreUnknownKeys = true
        encodeDefaults = true
        explicitNulls = false
    }

    private val okHttp: OkHttpClient = OkHttpClient.Builder()
        .addInterceptor(dynamicConfigInterceptor)
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()

    private val retrofit: Retrofit = Retrofit.Builder()
        .baseUrl(SettingsStore.DEFAULT_BASE_URL)
        .client(okHttp)
        .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
        .build()

    val api: ApiService = retrofit.create(ApiService::class.java)

    /** 设置变更时调用；地址非法时保留原值并返回 false */
    fun updateConfig(baseUrl: String, token: String): Boolean {
        val previous = baseUrlRef.get()
        val previousToken = tokenRef.get()
        baseUrlRef.set(baseUrl.trim())
        tokenRef.set(token.trim())
        val valid = baseUrl.trim() == SettingsStore.DEFAULT_BASE_URL || parseBaseUrl() != null
        if (!valid) {
            baseUrlRef.set(previous)
            tokenRef.set(previousToken)
            return false
        }
        return true
    }

    fun currentBaseUrl(): String = baseUrlRef.get()
}
