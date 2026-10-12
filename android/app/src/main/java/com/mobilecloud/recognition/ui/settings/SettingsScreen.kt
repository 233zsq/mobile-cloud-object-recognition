package com.mobilecloud.recognition.ui.settings

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.mobilecloud.recognition.ui.theme.BrandMark
import com.mobilecloud.recognition.ui.theme.FieldNotesHeader

enum class SettingsPage(val path: String, val title: String, val description: String) {
    OVERVIEW("", "我的手册", ""),
    CONNECTION("connection", "云端连接", "管理组内服务地址与访问口令"),
    MODEL("model", "识别模型", "查看当前模型与校验信息"),
    PRIVACY("privacy", "数据与隐私", "了解照片、记录与访问权限"),
    DIAGNOSTICS("diagnostics", "帮助与自检", "使用说明、模型检查与报告分享"),
}

/** A small overview leads to focused pages; their shared ViewModel retains drafts. */
@Composable
fun SettingsScreen(
    viewModel: SettingsViewModel = viewModel(),
    page: SettingsPage = SettingsPage.OVERVIEW,
    onOpenPage: (SettingsPage) -> Unit = {},
    onBack: () -> Unit = {},
) {
    val state = viewModel.state
    Column(Modifier.fillMaxSize()) {
        if (page == SettingsPage.OVERVIEW) {
            Column(Modifier.verticalScroll(rememberScrollState()).padding(bottom = 24.dp)) {
                FieldNotesHeader(page.title)
                SettingsOverview(state, onOpenPage)
            }
        } else {
            Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                IconButton(onClick = onBack, modifier = Modifier.testTag("settings-back")) {
                    Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回我的手册")
                }
                Text("我的手册", style = MaterialTheme.typography.labelLarge, modifier = Modifier.weight(1f))
                BrandMark(Modifier.size(36.dp))
                Spacer(Modifier.width(10.dp))
            }
            Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(start = 24.dp, end = 24.dp, bottom = 28.dp)) {
                Spacer(Modifier.height(14.dp))
                Text(page.title, style = MaterialTheme.typography.headlineMedium)
                Spacer(Modifier.height(8.dp))
                Text(page.description, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Spacer(Modifier.height(26.dp))
                when (page) {
                    SettingsPage.CONNECTION -> ConnectionSettings(state, viewModel)
                    SettingsPage.MODEL -> ModelSettings(state, viewModel)
                    SettingsPage.PRIVACY -> PrivacySettings(state)
                    SettingsPage.DIAGNOSTICS -> DiagnosticsSettings(state, viewModel)
                    SettingsPage.OVERVIEW -> Unit
                }
            }
        }
    }
}

@Composable
private fun SettingsOverview(state: SettingsUiState, onOpenPage: (SettingsPage) -> Unit) {
    Column(Modifier.padding(horizontal = 24.dp)) {
        Column(Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.primary, RoundedCornerShape(20.dp)).padding(18.dp)) {
            Text("随时观察，离线也可以。", style = MaterialTheme.typography.titleMedium, color = MaterialTheme.colorScheme.onPrimary)
            Spacer(Modifier.height(10.dp))
            Text("当前模型  ${state.modelInfo?.modelVersion ?: "正在检查"}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onPrimary.copy(alpha = .85f))
            Spacer(Modifier.height(10.dp))
            Text(
                if (state.modelInfo != null) "${state.modelInfo.labelsCount} 类物品 · 本地模型已校验" else state.modelError ?: "正在加载模型信息…",
                style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.primaryContainer,
            )
        }
        Spacer(Modifier.height(20.dp))
        Text("管理你的观察", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.height(8.dp))
        val pages = listOf(SettingsPage.CONNECTION, SettingsPage.MODEL, SettingsPage.PRIVACY, SettingsPage.DIAGNOSTICS)
        pages.forEachIndexed { index, page ->
            val detail = when (page) {
                SettingsPage.CONNECTION -> if (state.token.isBlank()) "地址与口令 · 尚未设置访问口令" else "地址、访问口令与连接检查"
                SettingsPage.MODEL -> state.modelInfo?.let { "${it.modelVersion} · ${it.labelsCount} 类" } ?: "查看版本、类别与校验状态"
                SettingsPage.PRIVACY -> "照片如何使用，记录如何保存"
                else -> "识别说明、20 张样例自检与报告"
            }
            Row(
                Modifier.fillMaxWidth().testTag("settings-${page.path}").clickable { onOpenPage(page) }.padding(vertical = 14.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Box(Modifier.size(38.dp).background(MaterialTheme.colorScheme.surfaceContainer, RoundedCornerShape(10.dp)), contentAlignment = Alignment.Center) {
                    Text("0${index + 1}", style = MaterialTheme.typography.labelMedium)
                }
                Spacer(Modifier.width(14.dp))
                Column(Modifier.weight(1f)) {
                    Text(page.title, style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(5.dp))
                    Text(detail, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, contentDescription = null, tint = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
        }
        Spacer(Modifier.height(20.dp))
        Text("CAMPUS / FIELD NOTES", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.height(5.dp))
        val context = LocalContext.current
        val version = remember(context) { context.packageManager.getPackageInfo(context.packageName, 0).versionName ?: "—" }
        Text("校园物品识别 · $version", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun ConnectionSettings(state: SettingsUiState, viewModel: SettingsViewModel) {
    Note("连接用于云端识别和记录同步。本地识别可以离线使用；修改后请先保存，再测试连接。")
    Spacer(Modifier.height(22.dp))
    OutlinedTextField(
        value = state.baseUrl, onValueChange = viewModel::onBaseUrlChange,
        label = { Text("服务器地址") }, supportingText = { Text("组内服务：https://49.232.195.47。仅填写服务根地址。") },
        singleLine = true, modifier = Modifier.fillMaxWidth().testTag("settings-server-url"), enabled = state.configLoaded && !state.saving,
    )
    Spacer(Modifier.height(16.dp))
    OutlinedTextField(
        value = state.token, onValueChange = viewModel::onTokenChange,
        label = { Text("访问口令") }, supportingText = { Text("由组内管理员提供，保存在此设备的应用私有设置中。") },
        visualTransformation = PasswordVisualTransformation(), singleLine = true,
        modifier = Modifier.fillMaxWidth(), enabled = state.configLoaded && !state.saving,
    )
    Spacer(Modifier.height(22.dp))
    Button(onClick = viewModel::save, enabled = state.configLoaded && !state.saving, modifier = Modifier.fillMaxWidth()) {
        Text(if (state.saving) "正在保存…" else "保存连接设置")
    }
    Spacer(Modifier.height(8.dp))
    OutlinedButton(onClick = viewModel::testConnection, enabled = state.configLoaded && !state.testing && !state.saving, modifier = Modifier.fillMaxWidth()) {
        Text(if (state.testing) "正在检查…" else "测试已保存的连接")
    }
    state.savedMessage?.let { ResultNote(it) }
    state.testResult?.let { ResultNote(it) }
}

@Composable
private fun ModelSettings(state: SettingsUiState, viewModel: SettingsViewModel) {
    Note("本地与云端使用同版模型，切换识别位置不会切换模型。当前版本随 App 提供，暂不支持在 App 内下载更新。")
    Spacer(Modifier.height(22.dp))
    state.modelInfo?.let { info ->
        Detail("模型版本", info.modelVersion)
        Detail("可识别物品", "${info.labelsCount} 类")
        Detail("低置信提醒阈值", "${(info.lowConfidenceThreshold * 100).toInt()}%")
        Text("低于阈值仍显示预测，请核对并按需修正。", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.height(24.dp))
        Text("技术信息", style = MaterialTheme.typography.titleSmall)
        Detail("模型校验摘要", info.sha256Short + "（SHA-256 前 8 位）")
        Detail("输入形状", info.inputShape.joinToString(" × "))
        info.categoryVersion?.let { Detail("类别版本", it) }
        Detail("归一化", info.normalization)
    } ?: ResultNote(state.modelError ?: "正在加载模型信息…", state.modelError != null)
    Spacer(Modifier.height(22.dp))
    OutlinedButton(onClick = viewModel::reloadModel, modifier = Modifier.fillMaxWidth()) { Text("重新校验本地模型") }
}

@Composable
private fun PrivacySettings(state: SettingsUiState) {
    Note("识别记录与照片分开处理。选择云端前，请确认画面适合发送至组内服务器。")
    Spacer(Modifier.height(24.dp))
    HelpItem("本地识别", "照片在本机处理，识别不需要网络。记录保存到本机，联网后同步分类、置信度、模型版本和时间等记录信息。")
    HelpItem("云端识别", "仅在选择云端后发送图片。App 生成去除 EXIF 和位置信息的压缩副本；服务处理后释放图片，不自动加入训练图库。画面内的个人信息仍可能可见。")
    HelpItem("访问口令", "用于组内接口认证，不包含在安装包中。请勿分享口令、手机备份或包含私有配置的文件。")
    HelpItem("本机记录", "在「记录」页可查看、纠错和同步。清空本地记录不删除云端已经保存的记录，筛选结果也不改变清空范围。")
    Spacer(Modifier.height(8.dp))
    Text("设备标识", style = MaterialTheme.typography.titleSmall)
    Spacer(Modifier.height(8.dp))
    SelectionContainer { Text(state.clientId.ifBlank { "正在读取…" }, style = MaterialTheme.typography.bodySmall) }
    Spacer(Modifier.height(8.dp))
    Text("首次启动生成，随记录上报以区分设备；它不是访问口令。", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
}

@Composable
private fun DiagnosticsSettings(state: SettingsUiState, viewModel: SettingsViewModel) {
    val context = LocalContext.current
    HelpItem("让识别更可靠", "每次保留一个主要物品，尽量拍全轮廓，避开遮挡和杂乱背景。低置信结果请人工核对，必要时重拍或修正类别。")
    HelpItem("云端连接失败", "先到「云端连接」保存正确地址与口令，再测试连接。失败的照片可重试，也可以手动转为本地识别。")
    HorizontalDivider()
    Spacer(Modifier.height(24.dp))
    Text("模型一致性自检", style = MaterialTheme.typography.titleMedium)
    Spacer(Modifier.height(10.dp))
    Text("使用 20 张随包样例核对参考输入和图片处理结果，不上传照片，不增加日常记录。报告可分享给项目组排查问题。", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
    Spacer(Modifier.height(18.dp))
    when {
        !state.examplesAvailable -> Note("此安装包未附带自检样例，请使用包含样例的 debug 版本。")
        state.checkRunning -> Row(verticalAlignment = Alignment.CenterVertically) {
            CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
            Spacer(Modifier.width(12.dp))
            Text(state.checkProgress ?: "正在检查…", style = MaterialTheme.typography.bodySmall)
        }
        else -> Button(onClick = viewModel::runConsistencyCheck, modifier = Modifier.fillMaxWidth()) { Text("开始自检 · 20 张样例") }
    }
    state.checkSummary?.let { ResultNote(it, state.checkFailed) }
    state.checkZipPath?.let { path ->
        Spacer(Modifier.height(12.dp))
        OutlinedButton(onClick = { shareReport(context, path) }, modifier = Modifier.fillMaxWidth()) { Text("分享自检报告") }
        Spacer(Modifier.height(8.dp))
        Text("报告包含设备信息、测试结果和参考张量，不包含访问口令。", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun Note(text: String) {
    Text(text, Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.surfaceContainer, RoundedCornerShape(12.dp)).padding(16.dp),
        style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
}

@Composable
private fun HelpItem(title: String, body: String) {
    Text(title, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
    Spacer(Modifier.height(8.dp))
    Text(body, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
    Spacer(Modifier.height(24.dp))
}

@Composable
private fun Detail(label: String, value: String) {
    Column(Modifier.fillMaxWidth().padding(vertical = 12.dp)) {
        Text(label, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.height(6.dp))
        SelectionContainer { Text(value, style = MaterialTheme.typography.bodyMedium) }
    }
    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
}

@Composable
private fun ResultNote(text: String, error: Boolean = false) {
    Spacer(Modifier.height(12.dp))
    Text(text, style = MaterialTheme.typography.bodySmall, color = if (error) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.primary)
}

/** Shares the existing local report; it never includes connection settings. */
private fun shareReport(context: android.content.Context, zipPath: String) {
    val file = java.io.File(zipPath)
    if (!file.exists()) return
    runCatching {
        val uri = androidx.core.content.FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", file)
        val intent = android.content.Intent(android.content.Intent.ACTION_SEND).apply {
            type = "application/zip"
            putExtra(android.content.Intent.EXTRA_STREAM, uri)
            addFlags(android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        context.startActivity(android.content.Intent.createChooser(intent, "分享一致性报告").addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK))
    }
}
