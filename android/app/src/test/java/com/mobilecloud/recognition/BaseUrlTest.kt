package com.mobilecloud.recognition

import com.mobilecloud.recognition.data.remote.BaseUrl
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class BaseUrlTest {

    @Test
    fun `http url with port parses`() {
        val parsed = BaseUrl.parse("http://192.168.1.10:8080")!!
        assertEquals("http", parsed.scheme)
        assertEquals("192.168.1.10", parsed.host)
        assertEquals(8080, parsed.port)
    }

    @Test
    fun `https defaults to port 443`() {
        assertEquals(443, BaseUrl.parse("https://example.com")!!.port)
    }

    @Test
    fun `http defaults to port 80`() {
        assertEquals(80, BaseUrl.parse("http://example.com")!!.port)
    }

    @Test
    fun `missing scheme is rejected`() {
        assertNull(BaseUrl.parse("192.168.1.10:8080"))
        assertFalse(BaseUrl.isValid("192.168.1.10:8080"))
    }

    @Test
    fun `blank and null are rejected`() {
        assertNull(BaseUrl.parse(null))
        assertNull(BaseUrl.parse("   "))
    }

    @Test
    fun `non http scheme is rejected`() {
        assertNull(BaseUrl.parse("ftp://example.com"))
        assertNull(BaseUrl.parse("file:///tmp/x"))
    }

    @Test
    fun `trailing path is tolerated for base url`() {
        // 只取 scheme/host/port；路径不参与拼接（接口路径由 Retrofit 注解提供）
        assertTrue(BaseUrl.isValid("http://example.com/api"))
    }
}