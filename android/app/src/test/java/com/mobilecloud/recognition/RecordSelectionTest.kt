package com.mobilecloud.recognition

import com.mobilecloud.recognition.data.local.RecordEntity
import com.mobilecloud.recognition.ui.records.selectRecords
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class RecordSelectionTest {
    private fun record(id: String, model: String, uploaded: Boolean = true, corrected: Boolean = false) =
        RecordEntity(
            recordId = id, clientId = "local-client", modelVersion = model,
            predictedIndex = 0, predictedLabel = "cup", confidence = 0.9f,
            latencyMs = 12, capturedAt = 1, updatedAt = 1, uploaded = uploaded,
            correctedLabel = if (corrected) "book" else null,
            correctionPending = corrected,
        )

    private val records = listOf(
        record("new", "campus-evolve-v2", corrected = true),
        record("old", "campus-gpu-v1", uploaded = false),
        record("synced", "campus-evolve-v2"),
    )

    @Test fun allModelsIncludesUploadsAndPendingCorrections() {
        val selection = selectRecords(records, null)
        assertEquals(records, selection.records)
        assertEquals(3, selection.count)
        assertEquals(2, selection.pendingCount)
        assertEquals(1, selection.correctedCount)
    }

    @Test fun filteringPreservesOrderAndUsesTheSelectedModelsCounts() {
        val selection = selectRecords(records, "campus-evolve-v2")
        assertEquals(listOf("new", "synced"), selection.records.map { it.recordId })
        assertEquals(2, selection.count)
        assertEquals(1, selection.pendingCount)
        assertEquals(1, selection.correctedCount)
        // Clear-all and sync-all still operate on the whole local database.
        assertEquals(3, selection.allCount)
        assertEquals(2, selection.allPendingCount)
        assertEquals(2, selection.modelVersions.size)
    }

    @Test fun exactVersionMatchDoesNotIncludeASimilarlyNamedVersion() {
        val data = records + record("v20", "campus-evolve-v20")
        assertEquals(2, selectRecords(data, "campus-evolve-v2").count)
        assertEquals(listOf("v20"), selectRecords(data, "campus-evolve-v20").records.map { it.recordId })
    }

    @Test fun deletingTheLastMatchingRecordKeepsAnEmptySelectionInsteadOfShowingOtherModels() {
        val selection = selectRecords(records.filter { it.modelVersion != "campus-gpu-v1" }, "campus-gpu-v1")
        assertTrue(selection.records.isEmpty())
        assertEquals("campus-gpu-v1", selection.modelVersion)
        assertTrue("campus-gpu-v1" in selection.modelVersions)
        assertEquals(2, selection.allCount)
    }

    @Test fun newModelAndSyncChangesAreReflectedWithoutHardcodedVersions() {
        val data = records.map { it.copy(uploaded = true, correctionPending = false) } + record("next", "future-v3")
        val selection = selectRecords(data, "campus-evolve-v2")
        assertEquals(0, selection.pendingCount)
        assertEquals(1, selection.correctedCount)
        assertTrue("future-v3" in selection.modelVersions)
        assertEquals(4, selectRecords(data, null).count)
    }

    @Test fun emptyLibraryHasNoStaleCounts() {
        val selection = selectRecords(emptyList(), null)
        assertTrue(selection.modelVersions.isEmpty())
        assertEquals(0, selection.count)
        assertEquals(0, selection.allCount)
        assertEquals(0, selection.allPendingCount)
    }
}
