package com.mobilecloud.recognition

import android.graphics.Bitmap
import android.os.ParcelFileDescriptor
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.v2.createAndroidComposeRule
import androidx.lifecycle.Lifecycle
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.rules.ExternalResource
import org.junit.runner.RunWith

/** Exercises actual CameraX frames and navigation without taking or uploading a photograph. */
@RunWith(AndroidJUnit4::class)
class LivePreviewUiTest {
    @get:Rule(order = 0) val cameraPermission = object : ExternalResource() {
        override fun before() {
            val instrumentation = InstrumentationRegistry.getInstrumentation()
            ParcelFileDescriptor.AutoCloseInputStream(instrumentation.uiAutomation.executeShellCommand(
                "pm grant ${instrumentation.targetContext.packageName} android.permission.CAMERA",
            )).use { it.readBytes() }
        }
    }
    @get:Rule(order = 1) val compose = createAndroidComposeRule<MainActivity>()

    @Test fun realCameraFramesTogglePauseAndResumeWithoutCreatingRecords() {
        val before = runBlocking { AppGraph.recordDao.count() }
        compose.waitUntil(20_000) {
            runCatching { compose.onNodeWithTag("live-recognition-toggle").assertIsEnabled() }.isSuccess
        }
        val toggle = compose.onNodeWithTag("live-recognition-toggle")
        toggle.assertIsOff().performClick().assertIsOn()
        compose.onNodeWithTag("live-recognition-overlay").assertIsDisplayed()
        // A percentage is displayed only after a real preview frame was decoded and inferred.
        compose.waitUntil(20_000) {
            compose.onAllNodesWithText("%", substring = true).fetchSemanticsNodes().isNotEmpty()
        }
        saveScreen("live-preview-on.png")
        compose.onNodeWithContentDescription("拍照识别").assertIsEnabled().assertIsDisplayed()
        compose.activityRule.scenario.moveToState(Lifecycle.State.CREATED)
        compose.activityRule.scenario.moveToState(Lifecycle.State.RESUMED)
        compose.onNodeWithTag("live-recognition-toggle").assertIsOn()
        compose.onNodeWithText("记录").performClick()
        compose.onNodeWithTag("live-recognition-overlay").assertDoesNotExist()
        compose.onNodeWithText("识别").performClick()
        compose.onNodeWithTag("live-recognition-toggle").assertIsOn()
        repeat(3) {
            toggle.performClick().assertIsOff()
            compose.onNodeWithTag("live-recognition-overlay").assertDoesNotExist()
            toggle.performClick().assertIsOn()
        }
        toggle.performClick().assertIsOff()
        saveScreen("live-preview-off.png")
        assertEquals(before, runBlocking { AppGraph.recordDao.count() })
    }

    private fun saveScreen(name: String) {
        val bitmap = compose.onRoot().captureToImage().asAndroidBitmap()
        val folder = requireNotNull(compose.activity.getExternalFilesDir("ui-checks")).apply { mkdirs() }
        File(folder, name).outputStream().use { check(bitmap.compress(Bitmap.CompressFormat.PNG, 100, it)) }
    }
}
