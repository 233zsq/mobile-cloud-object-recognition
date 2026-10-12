package com.mobilecloud.recognition.ui.capture

import android.Manifest
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.platform.testTag
import androidx.lifecycle.*
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.mobilecloud.recognition.data.CategoryCatalog
import com.mobilecloud.recognition.ui.theme.FieldNotesHeader

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CaptureScreen(catalog: CategoryCatalog, viewModel: CaptureViewModel = viewModel()) {
    val context = LocalContext.current
    val state by viewModel.state.collectAsStateWithLifecycle()
    val snackbar = remember { SnackbarHostState() }
    var permission by remember { mutableStateOf(hasCameraPermission(context)) }
    val permissionLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { permission = it }
    val importLauncher = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { it?.let(viewModel::onPhotoImport) }
    val launchImport = { importLauncher.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) }
    LaunchedEffect(Unit) { if (!permission) permissionLauncher.launch(Manifest.permission.CAMERA) }
    val owner = LocalLifecycleOwner.current
    DisposableEffect(owner) {
        val observer = LifecycleEventObserver { _, event -> if (event == Lifecycle.Event.ON_RESUME) permission = hasCameraPermission(context) }
        owner.lifecycle.addObserver(observer)
        onDispose { owner.lifecycle.removeObserver(observer) }
    }
    LaunchedEffect(state.message) {
        state.message?.let { snackbar.showSnackbar(it); viewModel.consumeMessage() }
    }
    val enabled = !state.capturing && (state.mode == InferenceMode.CLOUD || state.modelState is ModelState.Ready)
    Scaffold(snackbarHost = { SnackbarHost(snackbar) }) { padding ->
        Column(Modifier.fillMaxSize().padding(padding).verticalScroll(rememberScrollState())) {
            FieldNotesHeader("观察手册", "01 / 发现日常物品")
            InferenceModeSelector(state.mode, !state.capturing, viewModel::selectMode)
            Text(
                if (state.mode == InferenceMode.CLOUD) "图片发送至组内服务器 · 自动生成去除位置等元数据的压缩副本"
                else "在这台设备上识别 · 无需网络 · 照片保存在本机",
                Modifier.padding(horizontal = 22.dp, vertical = 8.dp),
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            if (state.mode == InferenceMode.DEVICE && state.modelState !is ModelState.Ready) {
                Row(Modifier.padding(horizontal = 22.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text(if (state.modelState is ModelState.Loading) "模型准备中…" else "本地模型不可用", Modifier.weight(1f))
                    if (state.modelState is ModelState.Error) TextButton(onClick = viewModel::loadModel) { Text("重新加载") }
                }
            }
            Box(Modifier.fillMaxWidth().heightIn(min = 280.dp).height(350.dp).padding(horizontal = 20.dp)) {
                if (permission) CameraCaptureView(enabled, viewModel::onPhotoSaved, viewModel::onCaptureError,
                    launchImport, onCaptureStarted = viewModel::onCaptureStarted)
                else Column(Modifier.fillMaxSize(), horizontalAlignment = Alignment.CenterHorizontally) {
                    CameraPermissionRationale({ permissionLauncher.launch(Manifest.permission.CAMERA) }, Modifier.weight(1f))
                    OutlinedButton(onClick = launchImport, enabled = enabled) { Text("导入图片识别") }
                }
            }
            if (state.capturing) Row(Modifier.padding(22.dp), verticalAlignment = Alignment.CenterVertically) {
                CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                Spacer(Modifier.width(10.dp))
                Text(if (state.mode == InferenceMode.CLOUD) "正在上传并识别…" else "正在观察…")
            }
            if (state.failedPhoto) Surface(
                modifier = Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 10.dp),
                color = MaterialTheme.colorScheme.errorContainer, shape = MaterialTheme.shapes.medium,
            ) {
                Column(Modifier.padding(14.dp)) {
                    Text(state.failure ?: "识别失败", color = MaterialTheme.colorScheme.onErrorContainer)
                    Text("照片已保留，本次未产生记录。", style = MaterialTheme.typography.bodySmall)
                    Row {
                        TextButton(onClick = { viewModel.retryPhoto() }, enabled = !state.capturing) { Text("重试这张照片") }
                        if (state.mode == InferenceMode.CLOUD) TextButton(
                            onClick = { viewModel.retryPhoto(useLocal = true) },
                            enabled = !state.capturing && state.modelState is ModelState.Ready,
                        ) { Text("改用本地") }
                    }
                }
            }
            state.lastResult?.let { ResultTicket(it, viewModel::startCorrection) }
            Spacer(Modifier.height(16.dp))
        }
    }
    if (state.showCorrectionSheet) {
        ModalBottomSheet(onDismissRequest = viewModel::dismissCorrection) {
            Column(Modifier.padding(22.dp)) {
                Text("选择正确类别", style = MaterialTheme.typography.headlineSmall)
                Text("保留原预测，追加人工修正。", style = MaterialTheme.typography.bodySmall)
                Spacer(Modifier.height(12.dp))
                catalog.categories.chunked(3).forEach { row ->
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        row.forEach { item ->
                            AssistChip(onClick = { viewModel.applyCorrection(item.id, item.displayName) }, label = { Text(item.displayName) })
                        }
                    }
                }
                Spacer(Modifier.height(24.dp))
            }
        }
    }
}

@Composable
internal fun InferenceModeSelector(mode: InferenceMode, enabled: Boolean, onSelect: (InferenceMode) -> Unit) {
    Row(Modifier.fillMaxWidth().padding(horizontal = 20.dp).background(MaterialTheme.colorScheme.surfaceContainer, RoundedCornerShape(28.dp)).padding(4.dp)) {
        InferenceMode.entries.forEach { item ->
            val selected = mode == item
            Box(
                Modifier.weight(1f).heightIn(min = 48.dp)
                    .background(if (selected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.surfaceContainer, RoundedCornerShape(24.dp))
                    .selectable(selected, enabled, Role.RadioButton) { onSelect(item) }
                    .testTag("inference-mode-" + item.key),
                contentAlignment = Alignment.Center,
            ) {
                Text(item.title, color = if (selected) MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.onSurface)
            }
        }
    }
}

@Composable
private fun ResultTicket(result: CaptureResult, onCorrect: () -> Unit) {
    Surface(Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 12.dp),
        shape = RoundedCornerShape(2.dp), color = MaterialTheme.colorScheme.surface,
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant)) {
        Column(Modifier.padding(18.dp)) {
            Text("OBSERVATION / " + result.recordId.take(8).uppercase() + " · " + if (result.source == InferenceMode.CLOUD) "CLOUD" else "LOCAL",
                style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Spacer(Modifier.height(10.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(result.correctedDisplayName ?: result.displayName, style = MaterialTheme.typography.headlineLarge)
                    if (result.correctedDisplayName != null) Text("原预测：" + result.displayName, style = MaterialTheme.typography.bodySmall)
                }
                Text("%.1f%%".format(result.prediction.confidence * 100), fontSize = 25.sp)
            }
            HorizontalDivider(Modifier.padding(vertical = 12.dp))
            Text(result.prediction.modelVersion, style = MaterialTheme.typography.labelSmall)
            Text(result.source.title + " · 预处理＋推理 " + result.prediction.totalMs + " ms", style = MaterialTheme.typography.bodySmall)
            if (result.source == InferenceMode.CLOUD) Text("本次总等待 " + result.elapsedMs + " ms（含上传、网络与解码）",
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            if (result.lowConfidence && result.correctedDisplayName == null) Text("需要确认 · 置信度较低", color = MaterialTheme.colorScheme.error)
            TextButton(onClick = onCorrect, contentPadding = PaddingValues(vertical = 4.dp, horizontal = 0.dp)) { Text("结果不对？修正类别") }
        }
    }
}
