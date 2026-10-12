package com.mobilecloud.recognition

import android.graphics.Bitmap
import android.os.ParcelFileDescriptor
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertTextContains
import androidx.compose.ui.test.assertIsSelected
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.junit4.v2.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextReplacement
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.rules.ExternalResource

/** Verifies navigation and SavedStateHandle ViewModel creation without changing records. */
@RunWith(AndroidJUnit4::class)
class RecordsScreenSmokeTest {
    @get:Rule(order = 0) val cameraPermission = object : ExternalResource() {
        override fun before() {
            val instrumentation = InstrumentationRegistry.getInstrumentation()
            val output = instrumentation.uiAutomation.executeShellCommand(
                "pm grant ${instrumentation.targetContext.packageName} android.permission.CAMERA",
            )
            ParcelFileDescriptor.AutoCloseInputStream(output).use { it.readBytes() }
        }
    }
    @get:Rule(order = 1) val compose = createAndroidComposeRule<MainActivity>()

    @Test fun historyOpensWithTheModelFilterAndCapturesTheCurrentLayout() {
        compose.onNodeWithText("记录").performClick()
        compose.onNodeWithText("观察记录").assertIsDisplayed()
        compose.onNodeWithTag("model-version-filter").assertTextContains("全部模型")
        val screenshot = compose.onRoot().captureToImage().asAndroidBitmap()
        val folder = requireNotNull(compose.activity.getExternalFilesDir("ui-checks")).apply { mkdirs() }
        File(folder, "records-model-filter.png").outputStream().use {
            check(screenshot.compress(Bitmap.CompressFormat.PNG, 100, it))
        }
    }

    @Test fun captureOffersExplicitLocalAndCloudModesWithoutSendingPhotos() {
        compose.onNodeWithText("观察手册").assertIsDisplayed()
        compose.onNodeWithTag("inference-mode-device").assertIsSelected()
        saveScreen("capture-field-notes-local.png")
        compose.onNodeWithTag("inference-mode-cloud").performClick().assertIsSelected()
        compose.onNodeWithText("图片发送至组内服务器", substring = true).performScrollTo().assertIsDisplayed()
        saveScreen("capture-field-notes-cloud.png")
        compose.onNodeWithTag("inference-mode-device").performClick().assertIsSelected()
    }

    @Test fun settingsPagesReturnToOverviewAndKeepUnsavedConnectionDrafts() {
        compose.onNodeWithText("我的").performClick()
        compose.onNodeWithText("我的手册").assertIsDisplayed()
        compose.onNodeWithTag("settings-server-url").assertDoesNotExist()
        saveScreen("settings-overview.png")
        compose.onNodeWithTag("settings-connection").performScrollTo().performClick()
        compose.waitUntil(5_000) {
            runCatching { compose.onNodeWithTag("settings-server-url").assertIsEnabled() }.isSuccess
        }
        val urlField = compose.onNodeWithTag("settings-server-url")
        val original = urlField.fetchSemanticsNode().config[SemanticsProperties.EditableText].text
        urlField.performTextReplacement("https://example.invalid")
        // Invoke the navigation back dispatcher, independent of the soft keyboard.
        compose.runOnUiThread { compose.activity.onBackPressedDispatcher.onBackPressed() }
        compose.onNodeWithTag("settings-connection").performScrollTo().performClick()
        compose.onNodeWithTag("settings-server-url").assertTextContains("https://example.invalid")
        compose.onNodeWithTag("settings-server-url").performTextReplacement(original)
        compose.onNodeWithTag("settings-back").performClick()
        compose.onNodeWithTag("settings-model").performScrollTo().performClick()
        compose.onNodeWithText("模型版本").assertIsDisplayed()
        saveScreen("settings-model.png")
        compose.onNodeWithTag("settings-back").performClick()
        compose.onNodeWithTag("settings-privacy").performScrollTo().performClick()
        compose.onNodeWithText("识别记录与照片分开处理。", substring = true).assertIsDisplayed()
        compose.onNodeWithTag("settings-back").performClick()
        compose.onNodeWithTag("settings-diagnostics").performScrollTo().performClick()
        compose.onNodeWithText("模型一致性自检").performScrollTo().assertIsDisplayed()
        compose.onNodeWithTag("settings-back").assertIsDisplayed().performClick()
        compose.onNodeWithTag("settings-server-url").assertDoesNotExist()
        compose.onNodeWithText("记录").performClick()
        compose.onNodeWithText("观察记录").assertIsDisplayed()
    }

    private fun saveScreen(name: String) {
        val bitmap = compose.onRoot().captureToImage().asAndroidBitmap()
        val folder = requireNotNull(compose.activity.getExternalFilesDir("ui-checks")).apply { mkdirs() }
        File(folder, name).outputStream().use { check(bitmap.compress(Bitmap.CompressFormat.PNG, 100, it)) }
    }
}
