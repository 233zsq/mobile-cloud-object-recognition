package com.mobilecloud.recognition

import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.mobilecloud.recognition.data.remote.CloudModelOption
import com.mobilecloud.recognition.ui.capture.CloudModelChoices
import com.mobilecloud.recognition.ui.theme.CampusRecognitionTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class CloudModelPickerTest {
    @get:Rule val compose = createComposeRule()
    private val v2 = CloudModelOption("campus-evolve-v2", "a".repeat(64), "campus-10-v4", "b".repeat(64), "进阶版 v2", "当前推荐版本", "frozen", emptyList(), .5f, true)
    @Test fun selectingAnotherCloudModelDoesNotChangeLocalModelOrEnableUnavailableChoices() {
        val selected = mutableStateOf(v2.version)
        val models = listOf(v2, v2.copy(version = "campus-gpu-v1", displayName = "基准版 v1", available = false))
        compose.setContent { CampusRecognitionTheme { CloudModelChoices(models, selected.value, true) { selected.value = it } } }
        compose.onNodeWithTag("cloud-model-campus-evolve-v2").assertIsSelected()
        compose.onNodeWithTag("cloud-model-campus-gpu-v1").assertIsNotEnabled()
        assertEquals("campus-evolve-v2", selected.value)
    }
    @Test fun aReadyAlternateModelCanBeSelectedAndControlsLockDuringInference() {
        val selected = mutableStateOf(v2.version)
        val enabled = mutableStateOf(true)
        val models = listOf(v2, v2.copy(version = "campus-gpu-v1", displayName = "基准版 v1"))
        compose.setContent { CampusRecognitionTheme { CloudModelChoices(models, selected.value, enabled.value) { selected.value = it } } }
        compose.onNodeWithTag("cloud-model-campus-gpu-v1").performClick().assertIsSelected()
        compose.runOnIdle { enabled.value = false }
        compose.onNodeWithTag("cloud-model-campus-evolve-v2").assertIsNotEnabled()
        assertEquals("campus-gpu-v1", selected.value)
    }
}
