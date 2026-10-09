package com.mobilecloud.recognition.data.remote

import com.mobilecloud.recognition.data.settings.ServerConfig
import java.net.URI
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference
import kotlinx.serialization.json.Json
import okhttp3.HttpUrl
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import retrofit2.Retrofit
import retrofit2.converter.kotlinx.serialization.asConverterFactory

/**
 * Retrofit 客户端。服务器地址与令牌以单个 [ServerConfig] 快照保存，
 * 拦截器每个请求只读取一次快照（地址与令牌必然同源，见 [RequestRewriter]），
 * 设置页修改后即时生效，无需重装。
 */
class ApiClient {

    /** 原子替换的配置快照：更新与读取都以整个对象为单位 */
    private val configRef = AtomicReference(ServerConfig.DEFAULT)

    private val dynamicConfigInterceptor = Interceptor { chain ->
        val snapshot = configRef.get()
        val plan = RequestRewriter.plan(chain.request().url.toString(), snapshot)
        val original = chain.request()
        val rewrittenUrl: HttpUrl = original.url.newBuilder().apply {
            plan.scheme?.let { scheme(it) }
            plan.host?.let { host(it) }
            plan.port?.let { port(it) }
        }.build()
        val request = original.newBuilder().url(rewrittenUrl).let { builder ->
            plan.token?.let { builder.header("Authorization", "Bearer $it") } ?: builder
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
        .baseUrl(ServerConfig.DEFAULT.baseUrl)
        .client(okHttp)
        .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
        .build()

    val api: ApiService = retrofit.create(ApiService::class.java)

    /** 设置变更时调用，整份快照原子替换；地址非法时保留原值并返回 false */
    fun updateConfig(config: ServerConfig): Boolean {
        if (!isAcceptable(config.baseUrl)) return false
        configRef.set(config)
        return true
    }

    fun currentConfig(): ServerConfig = configRef.get()

    private fun isAcceptable(baseUrl: String): Boolean {
        val trimmed = baseUrl.trim()
        return trimmed == ServerConfig.DEFAULT.baseUrl || BaseUrl.isValid(trimmed)
    }
}