package com.mobilecloud.recognition

import com.mobilecloud.recognition.data.remote.ServerErrorParser
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 服务端统一错误结构解析（backend/app/errors.py）：
 * 联调时必须以错误码为准，只按状态码映射会误导（PR 联调修复项）。
 */
class ServerErrorParserTest {

    @Test
    fun `parses official error envelope`() {
        val body = """{"error":{"code":"UNKNOWN_MODEL_VERSION","message":"模型版本尚未登记。"},"request_id":"abc"}"""
        val parsed = ServerErrorParser.parse(body)!!
        assertEquals("UNKNOWN_MODEL_VERSION", parsed.code)
        assertEquals("模型版本尚未登记。", parsed.message)
    }

    @Test
    fun `describe surfaces code, message and hint`() {
        val body = """{"error":{"code":"UNKNOWN_MODEL_VERSION","message":"模型版本尚未登记。"}}"""
        val text = ServerErrorParser.describe(400, body, "服务端拒绝：字段校验未通过（HTTP 400）")
        assertTrue(text, text.contains("模型版本尚未登记"))
        assertTrue(text, text.contains("UNKNOWN_MODEL_VERSION"))
        assertTrue(text, text.contains("register-model"))
        assertTrue(text, text.contains("HTTP 400"))
    }

    @Test
    fun `describe falls back to status code mapping when body is not structured`() {
        val fallback = "上报失败（HTTP 502）"
        assertEquals(fallback, ServerErrorParser.describe(502, "<html>bad gateway</html>", fallback))
        assertEquals(fallback, ServerErrorParser.describe(502, null, fallback))
        assertEquals(fallback, ServerErrorParser.describe(502, "", fallback))
    }

    @Test
    fun `parse tolerates unknown fields and missing message`() {
        val parsed = ServerErrorParser.parse("""{"error":{"code":"RECORD_CONFLICT"},"extra":1}""")!!
        assertEquals("RECORD_CONFLICT", parsed.code)
        assertEquals("", parsed.message)
        assertNull(ServerErrorParser.parse("""{"unrelated":true}"""))
    }

    @Test
    fun `known codes carry actionable hints`() {
        assertEquals(true, ServerErrorParser.hint("RECORD_CONFLICT")!!.contains("同 UUID"))
        assertEquals(true, ServerErrorParser.hint("UNKNOWN_CATEGORY")!!.contains("类别"))
        assertNull(ServerErrorParser.hint("SOMETHING_ELSE"))
    }
}