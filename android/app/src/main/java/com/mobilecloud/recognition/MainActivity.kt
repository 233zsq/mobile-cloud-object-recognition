package com.mobilecloud.recognition

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import com.mobilecloud.recognition.ui.AppRoot
import com.mobilecloud.recognition.ui.theme.CampusRecognitionTheme

/**
 * 应用入口：初始化服务定位器（含网络回调注册），托管 Compose 导航。
 */
class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        AppGraph.init(this)
        super.onCreate(savedInstanceState)
        setContent {
            CampusRecognitionTheme {
                AppRoot()
            }
        }
    }
}
