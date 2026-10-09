package com.mobilecloud.recognition

import com.mobilecloud.recognition.data.local.RecordEntity
import com.mobilecloud.recognition.sync.RecordMapper
import java.time.ZoneId
import org.junit.Assert.assertEquals
import org.junit.Test

class RecordMapperTest {

    private val entity = RecordEntity(
        recordId = "11111111-2222-3333-4444-555555555555",
        clientId = "client-1",
        modelVersion = "placeholder-random-v0",
        predictedIndex = 5,
        predictedLabel = "keyboard",
        confidence = 0.874f,
        latencyMs = 123,
        capturedAt = 1_760_000_000_000, // 2025-10-09T08:26:40Z 附近，断言只看格式
        photoPath = "/data/photos/a.jpg",
        updatedAt = 1_760_000_000_000,
    )

    @Test
    fun `upload request maps original prediction only`() {
        val request = RecordMapper.toUploadRequest(entity)
        assertEquals(entity.recordId, request.recordId)
        assertEquals("client-1", request.clientId)
        assertEquals("device", request.inferenceSource)
        assertEquals("placeholder-random-v0", request.modelVersion)
        assertEquals(5, request.predictedId)
        assertEquals(0.874f, request.confidence)
        assertEquals(123L, request.latencyMs)
    }

    @Test
    fun `correction request carries revision`() {
        val corrected = entity.copy(correctedIndex = 3, correctedAt = 1_760_000_100_000, revision = 2)
        val request = RecordMapper.toCorrectionRequest(corrected)
        assertEquals(3, request.correctedId)
        assertEquals(2, request.revision)
    }

    @Test
    fun `iso time keeps zone offset`() {
        val zone = ZoneId.of("+08:00")
        val iso = RecordMapper.isoTime(1_760_000_000_000, zone)
        // 固定 +08:00 时区：UTC 2025-10-09T08:53:20Z 对应本地 16:53:20
        assertEquals("2025-10-09T16:53:20.000+08:00", iso)
    }

    @Test
    fun `error messages cover conflict and auth`() {
        assertEquals(true, RecordMapper.uploadErrorMessage(409).contains("冲突"))
        assertEquals(true, RecordMapper.uploadErrorMessage(401).contains("认证"))
        assertEquals(true, RecordMapper.uploadErrorMessage(503).contains("服务端"))
    }

    @Test
    fun `pending sync reflects both upload and correction states`() {
        assertEquals(true, entity.pendingSync)
        val uploaded = entity.copy(uploaded = true)
        assertEquals(false, uploaded.pendingSync)
        val correctionPending = uploaded.copy(correctionPending = true)
        assertEquals(true, correctionPending.pendingSync)
    }
}
