package com.mobilecloud.recognition

import com.mobilecloud.recognition.data.remote.CloudModelOption
import com.mobilecloud.recognition.data.remote.CloudModelsResponse
import com.mobilecloud.recognition.inference.validated
import com.mobilecloud.recognition.util.ShaUtil
import org.junit.Assert.*
import org.junit.Test

class CloudModelCatalogTest {
    private val labels = listOf("cup", "umbrella", "book", "pencil_case", "mouse", "keyboard", "earphones", "charger", "key", "backpack")
    private val labelsHash = ShaUtil.sha256Hex((labels.joinToString("\n") + "\n").toByteArray())
    private val v2 = CloudModelOption("campus-evolve-v2", "a".repeat(64), "campus-10-v4", labelsHash, "进阶版 v2", "当前推荐版本", "frozen", labels, .5f, true)
    private val v1 = v2.copy(version = "campus-gpu-v1", sha256 = "b".repeat(64), threshold = .6f, available = false)
    @Test fun catalogRetainsSeparateContractsAndUnavailableEntries() {
        val catalog = CloudModelsResponse(v2.version, listOf(v2, v1)).validated(labels)
        assertEquals(.6f, catalog.models[1].threshold, 0f)
        assertFalse(catalog.models[1].available)
        assertEquals(v2.version, catalog.defaultModelVersion)
    }
    @Test fun duplicateMissingDefaultOrUnboundedCatalogIsRejected() {
        listOf(CloudModelsResponse(v2.version, listOf(v2, v2)), CloudModelsResponse("missing", listOf(v2)),
            CloudModelsResponse(v2.version, emptyList()), CloudModelsResponse(v2.version, (1..5).map { v2.copy(version = "model-$it") }))
            .forEach { assertThrows(IllegalArgumentException::class.java) { it.validated(labels) } }
    }
    @Test fun thirdApprovedModelCanCoexistWithV2AndV1() {
        assertEquals(3, CloudModelsResponse(v2.version, listOf(v2, v1, v2.copy(version = "campus-evolve-v3"))).validated(labels).models.size)
    }
    @Test fun mismatchedHashLabelsThresholdOrUnapprovedModelIsRejected() {
        listOf(v2.copy(sha256 = "wrong"), v2.copy(labelsSha256 = "0".repeat(64)), v2.copy(labels = labels.reversed()),
            v2.copy(threshold = Float.NaN), v2.copy(threshold = 1.1f), v2.copy(status = "experimental"))
            .forEach { assertThrows(IllegalArgumentException::class.java) { CloudModelsResponse(it.version, listOf(it)).validated(labels) } }
    }
}
