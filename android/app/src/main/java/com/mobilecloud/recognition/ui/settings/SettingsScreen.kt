package com.mobilecloud.recognition.ui.settings

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel

/**
 * 设置页：服务器地址与令牌、连接测试、模型包信息（F05 联调辅助 + T04 验证）。
 */
@Composable
fun SettingsScreen(viewModel: SettingsViewModel = viewModel()) {
    var baseUrl by remember { mutableStateOf("") }
    var token by remember { mutableStateOf("") }
    var initialized by remember { mutableStateOf(false) }

    // 首次把持久化值同步进输入框；此后以本地输入为准，保存按钮统一提交
    if (!initialized && viewModel.state.baseUrl.isNotEmpty()) {
        baseUrl = viewModel.state.baseUrl
        token = viewModel.state.token
        initialized = true
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
    ) {
        Text("设置", style = MaterialTheme.typography.titleLarge)
        Spacer(Modifier.height(12.dp))

        OutlinedTextField(
            value = baseUrl,
            onValueChange = { baseUrl = it; viewModel.onBaseUrlChange(it) },
            label = { Text("服务器地址") },
            supportingText = { Text("如 http://192.168.1.10:8080，联调时填写腾讯云或内网地址") },
            modifier = Modifier.fillMaxWidth(),
            singleLine = true,
        )
        Spacer(Modifier.height(8.dp))
        OutlinedTextField(
            value = token,
            onValueChange = { token = it; viewModel.onTokenChange(it) },
            label = { Text("访问令牌（可选）") },
            modifier = Modifier.fillMaxWidth(),
            singleLine = true,
        )
        Spacer(Modifier.height(8.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Button(onClick = viewModel::save, enabled = !viewModel.state.saving) {
                Text("保存")
            }
            Spacer(Modifier.width(8.dp))
            OutlinedButton(
                onClick = viewModel::testConnection,
                enabled = !viewModel.state.testing,
            ) {
                if (viewModel.state.testing) {
                    CircularProgressIndicator(modifier = Modifier.height(16.dp), strokeWidth = 2.dp)
                } else {
                    Text("测试连接")
                }
            }
        }
        viewModel.state.savedMessage?.let {
            Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.primary)
        }
        viewModel.state.testResult?.let {
            Spacer(Modifier.height(4.dp))
            Text(it, style = MaterialTheme.typography.bodySmall)
        }

        Spacer(Modifier.height(16.dp))
        HorizontalDivider()
        Spacer(Modifier.height(12.dp))

        Text("模型信息", style = MaterialTheme.typography.titleMedium)
        Spacer(Modifier.height(6.dp))
        val info = viewModel.state.modelInfo
        if (info != null) {
            Text("版本：${info.modelVersion}", style = MaterialTheme.typography.bodySmall)
            Text("SHA-256 前8位：${info.sha256Short}", style = MaterialTheme.typography.bodySmall)
            Text("标签数：${info.labelsCount}", style = MaterialTheme.typography.bodySmall)
            Text("输入形状：${info.inputShape.joinToString("×")}", style = MaterialTheme.typography.bodySmall)
            Text("低置信阈值：${info.lowConfidenceThreshold}", style = MaterialTheme.typography.bodySmall)
            info.categoryVersion?.let {
                Text("类别版本：$it", style = MaterialTheme.typography.bodySmall)
            }
        } else {
            Text(
                viewModel.state.modelError ?: "未加载",
                style = MaterialTheme.typography.bodySmall,
                color = if (viewModel.state.modelError != null) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurface,
            )
        }
        Spacer(Modifier.height(6.dp))
        OutlinedButton(onClick = viewModel::reloadModel) { Text("重新校验模型包") }

        Spacer(Modifier.height(16.dp))
        HorizontalDivider()
        Spacer(Modifier.height(12.dp))

        Text("本机客户端标识", style = MaterialTheme.typography.titleMedium)
        Spacer(Modifier.height(4.dp))
        Text(viewModel.state.clientId, style = MaterialTheme.typography.bodySmall)
        Text(
            "client_id 首次启动生成并固定，上报时随记录发送，服务端用于区分设备",
            style = MaterialTheme.typography.bodySmall,
        )
    }
}
