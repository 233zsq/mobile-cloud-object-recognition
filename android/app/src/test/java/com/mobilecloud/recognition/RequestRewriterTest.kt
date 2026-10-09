package com.mobilecloud.recognition

import com.mobilecloud.recognition.data.remote.RequestRewriter
import com.mobilecloud.recognition.data.settings.ServerConfig
import com.mobilecloud.recognition.data.settings.SettingsPolicy
import com.mobilecloud.recognition.data.settings.SettingsStore
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class RequestRewriterTest {

    private val serverA = ServerConfig("https://a.example.com:8443", "token-A")
    private val serverB = ServerConfig("http://192.168.1.10:8080", "token-B")

    @Test
    fun `host and token always come from the same snapshot`() {
        val planA = RequestRewriter.plan("https://placeholder/api/records", serverA)
        assertEquals("https", planA.scheme)
        assertEquals("a.example.com", planA.host)
        assertEquals(8443, planA.port)
        assertEquals("token-A", planA.token)

        val planB = RequestRewriter.plan("https://placeholder/api/records", serverB)
        assertEquals("192.168.1.10", planB.host)
        assertEquals("token-B", planB.token)
    }

    @Test
    fun `default placeholder config rewrites nothing and sends no token`() {
        val plan = RequestRewriter.plan("http://localhost:8080/api/health", ServerConfig.DEFAULT)
        assertNull(plan.host)
        assertNull(plan.token)
    }

    @Test
    fun `blank token is not sent`() {
        val plan = RequestRewriter.plan("https://placeholder/x", serverA.copy(token = "   "))
        assertNull(plan.token)
    }

    @Test
    fun `invalid base url yields no rewrite`() {
        val plan = RequestRewriter.plan("https://placeholder/x", ServerConfig("not-a-url", "t"))
        assertNull(plan.host)
        assertEquals("t", plan.token) // 令牌仍按快照处理，但请求会打到占位地址并快速失败
    }
}

class SettingsPolicyTest {

    @Test
    fun `default and valid urls are accepted`() {
        assertNull(SettingsPolicy.validateForSave(ServerConfig.DEFAULT))
        assertNull(SettingsPolicy.validateForSave(ServerConfig(SettingsStore.TEAM_SERVER_URL, "t")))
        assertNull(SettingsPolicy.validateForSave(ServerConfig("http://192.168.1.10:8080", "")))
    }

    @Test
    fun `port above 65535 is rejected before persisting`() {
        val reason = SettingsPolicy.validateForSave(ServerConfig("https://49.232.195.47:70000", "t"))
        assertTrue(reason!!.contains("端口"))
        assertTrue(reason.contains("未保存"))
    }

    @Test
    fun `port zero and missing scheme are rejected`() {
        assertTrue(
            SettingsPolicy.validateForSave(ServerConfig("https://host:0", "t"))!!.contains("无效"),
        )
        assertTrue(
            SettingsPolicy.validateForSave(ServerConfig("192.168.1.10:8080", "t"))!!.contains("无效"),
        )
    }

    @Test
    fun `blank url is rejected`() {
        assertTrue(SettingsPolicy.validateForSave(ServerConfig("   ", "t"))!!.contains("不能为空"))
    }
}