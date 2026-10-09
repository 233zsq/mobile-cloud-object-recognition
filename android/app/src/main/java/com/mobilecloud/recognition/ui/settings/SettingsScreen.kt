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
import androidx.compose.ui.platform.LocalContext

/**
 * 设置页：服务器地址与令牌、连接测试、模型包信息（F05 联调辅助 + T04 验证）。
 */
@Composable
fun SettingsScreen(viewModel: SettingsViewModel = viewModel()) {
    val context = LocalContext.current
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
            supportingText = {
                Text(
                    "组内已部署：https://49.232.195.47（自签证书已内置信任，需填令牌）；" +
                        "局域网联调如 http://192.168.1.10:8080",
                )
            },
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
            Text("归一化：${info.normalization}", style = MaterialTheme.typography.bodySmall)
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

        Spacer(Modifier.height(16.dp))
        HorizontalDivider()
        Spacer(Modifier.height(12.dp))

        Text("端云一致性自检", style = MaterialTheme.typography.titleMedium)
        Spacer(Modifier.height(4.dp))
        Text(
            "对发布包附带的 20 张交接样例运行「参考张量」与「图片链路」两种对照，报告与输入张量" +
                "写入应用外部目录并打包，供仓库 verify 工具正式判定（T05/M02–M04）。",
            style = MaterialTheme.typography.bodySmall,
        )
        Spacer(Modifier.height(8.dp))
        if (!viewModel.state.examplesAvailable) {
            Text(
                "自检样例未打包（样例仅包含在 debug 构建中），请使用含样例的 debug 版本",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error,
            )
        } else if (viewModel.state.checkRunning) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                CircularProgressIndicator(modifier = Modifier.height(16.dp), strokeWidth = 2.dp)
                Spacer(Modifier.width(8.dp))
                Text(viewModel.state.checkProgress ?: "运行中…", style = MaterialTheme.typography.bodySmall)
            }
        } else {
            Button(onClick = viewModel::runConsistencyCheck) { Text("运行自检（20 张样例）") }
        }
        viewModel.state.checkSummary?.let { summary ->
            Spacer(Modifier.height(8.dp))
            Text(
                summary,
                style = MaterialTheme.typography.bodySmall,
                color = if (viewModel.state.checkFailed) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.primary,
            )
        }
        viewModel.state.checkZipPath?.let { zipPath ->
            Spacer(Modifier.height(8.dp))
            OutlinedButton(onClick = { shareReport(context, zipPath) }) { Text("分享报告压缩包") }
            Text(
                "也可通过 USB 从 Android/data/${context.packageName}/files/consistency/ 复制",
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

/** 通过 FileProvider 分享自检报告 zip（微信传回电脑最方便） */
private fun shareReport(context: android.content.Context, zipPath: String) {
    val file = java.io.File(zipPath)
    if (!file.exists()) return
    runCatching {
        val uri = androidx.core.content.FileProvider.getUriForFile(
            context,
            "${context.packageName}.fileprovider",
            file,
        )
        val intent = android.content.Intent(android.content.Intent.ACTION_SEND).apply {
            type = "application/zip"
            putExtra(android.content.Intent.EXTRA_STREAM, uri)
            addFlags(android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        context.startActivity(
            android.content.Intent.createChooser(intent, "分享一致性报告").addFlags(
                android.content.Intent.FLAG_ACTIVITY_NEW_TASK,
            ),
        )
    }
}
