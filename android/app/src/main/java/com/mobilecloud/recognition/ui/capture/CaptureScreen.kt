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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.*
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.mobilecloud.recognition.data.CategoryCatalog
import com.mobilecloud.recognition.data.remote.CloudModelOption
import com.mobilecloud.recognition.ui.theme.FieldNotesHeader
import com.mobilecloud.recognition.inference.LiveObservation
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CaptureScreen(catalog: CategoryCatalog, viewModel: CaptureViewModel = viewModel()) {
    val context = LocalContext.current
    val state by viewModel.state.collectAsStateWithLifecycle()
    val snackbar = remember { SnackbarHostState() }
    val scroll = rememberScrollState()
    var modelSheet by remember { mutableStateOf(false) }
    var confirmationSheet by remember { mutableStateOf(false) }
    var permission by remember { mutableStateOf(hasCameraPermission(context)) }
    var pickerOpen by remember { mutableStateOf(false) }
    val permissionLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { permission = it }
    val importLauncher = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) {
        pickerOpen = false
        it?.let(viewModel::onPhotoImport)
    }
    val launchImport = {
        viewModel.setLivePreviewActive(false)
        pickerOpen = true
        importLauncher.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly))
    }
    LaunchedEffect(Unit) { if (!permission) permissionLauncher.launch(Manifest.permission.CAMERA) }
    val owner = LocalLifecycleOwner.current
    var resumed by remember(owner) { mutableStateOf(owner.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)) }
    DisposableEffect(owner) {
        val observer = LifecycleEventObserver { _, event ->
            resumed = owner.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)
            if (!resumed) viewModel.setLivePreviewActive(false)
            if (event == Lifecycle.Event.ON_RESUME) {
                permission = hasCameraPermission(context)
                if (viewModel.state.value.mode == InferenceMode.CLOUD) viewModel.refreshCloudModels()
            }
        }
        owner.lifecycle.addObserver(observer)
        onDispose { owner.lifecycle.removeObserver(observer); viewModel.setLivePreviewActive(false) }
    }
    val liveRequested = resumed && permission && state.liveEnabled && state.liveCameraReady &&
        state.mode == InferenceMode.DEVICE && state.modelState is ModelState.Ready &&
        !state.capturing && state.confirmation == null && !pickerOpen && !modelSheet && !state.showCorrectionSheet
    DisposableEffect(liveRequested) {
        viewModel.setLivePreviewActive(liveRequested)
        onDispose { viewModel.setLivePreviewActive(false) }
    }
    LaunchedEffect(state.liveActive) {
        while (state.liveActive) { delay(250); viewModel.expireLiveObservation() }
    }
    LaunchedEffect(state.message) { state.message?.let { snackbar.showSnackbar(it); viewModel.consumeMessage() } }
    LaunchedEffect(state.lastResult?.recordId, state.confirmation) {
        if (state.lastResult != null || state.confirmation != null) { delay(120); scroll.animateScrollTo(scroll.maxValue) }
    }
    val selectedCloud = state.cloudModels.firstOrNull { it.version == state.cloudModelVersion }
    val enabled = !state.capturing && state.confirmation == null && if (state.mode == InferenceMode.CLOUD)
        selectedCloud?.available == true && !state.cloudModelsLoading else state.modelState is ModelState.Ready
    Scaffold(containerColor = MaterialTheme.colorScheme.background, snackbarHost = { SnackbarHost(snackbar) }) { padding ->
      BoxWithConstraints(Modifier.fillMaxSize().padding(padding)) {
        val compact = maxHeight < 640.dp
        val cameraHeight = (maxHeight - if (state.mode == InferenceMode.CLOUD) 320.dp else 280.dp).coerceIn(210.dp, 360.dp)
        Column(Modifier.fillMaxSize().verticalScroll(scroll).padding(bottom = 18.dp)) {
            FieldNotesHeader("观察手册")
            Row(Modifier.fillMaxWidth().padding(horizontal = 22.dp, vertical = if (compact) 8.dp else 12.dp), verticalAlignment = Alignment.Bottom) {
                Text("发现身边的\n小事物。", Modifier.weight(1f), fontFamily = FontFamily.Serif,
                    fontSize = if (compact) 28.sp else 34.sp, lineHeight = if (compact) 34.sp else 40.sp, fontWeight = FontWeight.Medium)
                NoteChip("10 类日常物品")
            }
            InferenceModeSelector(state.mode, !state.capturing && state.confirmation == null, viewModel::selectMode)
            if (state.mode == InferenceMode.CLOUD) {
                Surface(onClick = { modelSheet = true }, enabled = !state.capturing,
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 22.dp, vertical = 9.dp).testTag("cloud-model-picker"),
                    color = MaterialTheme.colorScheme.surface, shape = RoundedCornerShape(14.dp),
                    border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant)) {
                    Row(Modifier.padding(horizontal = 14.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(if (state.cloudModelsLoading) "正在读取云端模型…" else selectedCloud?.displayName ?: "选择云端模型",
                                style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
                            Text(selectedCloud?.version ?: "需要已保存的连接与访问口令", style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        Text("更换 ↓", style = MaterialTheme.typography.labelMedium)
                    }
                }
            } else {
                val localVersion = (state.modelState as? ModelState.Ready)?.info?.modelVersion?.substringAfterLast('-') ?: "准备中"
                LiveRecognitionControl(state.liveEnabled, permission && enabled && state.liveCameraReady,
                    localVersion, viewModel::setLiveEnabled)
            }
            if (state.mode == InferenceMode.DEVICE && state.modelState !is ModelState.Ready) {
                Row(Modifier.padding(horizontal = 22.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text(if (state.modelState is ModelState.Loading) "本地模型准备中…" else "本地模型不可用", Modifier.weight(1f))
                    if (state.modelState is ModelState.Error) TextButton(onClick = viewModel::loadModel) { Text("重新加载") }
                }
            }
            state.cloudModelsError?.takeIf { state.mode == InferenceMode.CLOUD }?.let {
                Row(Modifier.padding(horizontal = 22.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text(it, Modifier.weight(1f), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
                    TextButton(onClick = viewModel::refreshCloudModels, enabled = !state.capturing && !state.cloudModelsLoading) { Text("重试") }
                }
            }
            Box(Modifier.fillMaxWidth().height(if (permission) cameraHeight else 360.dp).padding(horizontal = 20.dp)) {
                if (permission) CameraCaptureView(enabled, viewModel::onPhotoSaved, viewModel::onCaptureError,
                    launchImport, onCaptureStarted = viewModel::onCaptureStarted,
                    liveActive = state.liveActive,
                    onAnalyzeFrame = { image -> runBlocking { viewModel.analyzePreviewFrame(image) } },
                    onLiveCameraReady = viewModel::setLiveCameraReady,
                    onLiveCameraUnavailable = viewModel::onLiveCameraUnavailable,
                    liveOverlay = if (state.liveEnabled && state.mode == InferenceMode.DEVICE) ({
                        LiveRecognitionOverlay(state.liveObservation, state.liveActive,
                            state.liveError, catalog::displayNameForLabel)
                    }) else null)
                else Column(Modifier.fillMaxSize(), horizontalAlignment = Alignment.CenterHorizontally) {
                    CameraPermissionRationale({ permissionLauncher.launch(Manifest.permission.CAMERA) }, Modifier.weight(1f))
                    OutlinedButton(onClick = launchImport, enabled = enabled) { Text("导入图片识别") }
                }
            }
            Text(if (state.mode == InferenceMode.CLOUD) "图片发送至组内服务器，仅用于本次识别。" else "照片留在本机，仅同步识别记录。",
                Modifier.padding(horizontal = 24.dp, vertical = 4.dp), style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
            if (state.capturing) Row(Modifier.padding(22.dp), verticalAlignment = Alignment.CenterVertically) {
                CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                Spacer(Modifier.width(10.dp))
                Text(if (state.mode == InferenceMode.CLOUD) "正在用所选模型识别…" else "正在观察…")
            }
            if (state.failedPhoto) Surface(Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 10.dp),
                color = MaterialTheme.colorScheme.errorContainer, shape = RoundedCornerShape(16.dp)) {
                Column(Modifier.padding(16.dp)) {
                    Text(state.failure ?: "识别失败", color = MaterialTheme.colorScheme.onErrorContainer)
                    Text("照片已保留，本次未产生记录。", style = MaterialTheme.typography.bodySmall)
                    Row {
                        TextButton(onClick = { viewModel.retryPhoto() }, enabled = !state.capturing) { Text("重试这张照片") }
                        if (state.mode == InferenceMode.CLOUD) TextButton(onClick = { viewModel.retryPhoto(useLocal = true) },
                            enabled = !state.capturing && state.modelState is ModelState.Ready) { Text("改用本地") }
                    }
                }
            }
            state.confirmation?.let { candidate ->
                PhotoConfirmationCard(candidate, !state.capturing,
                    { viewModel.confirmPhoto(candidate.prediction.index) }, { confirmationSheet = true }, viewModel::discardConfirmation)
            }
            if (state.confirmation == null) state.lastResult?.let { ResultTicket(it, viewModel::startCorrection) }
        }
      }
    }
    if (confirmationSheet && state.confirmation != null) ModalBottomSheet(onDismissRequest = { confirmationSheet = false }) {
        Column(Modifier.padding(22.dp)) {
            Text("确认类别并保存", style = MaterialTheme.typography.headlineSmall)
            Text("选一个实际类别；如果不属于这十类，请返回并选择不保存。", style = MaterialTheme.typography.bodySmall)
            catalog.categories.chunked(2).forEach { row -> Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                row.forEach { item -> AssistChip(enabled = !state.capturing,
                    modifier = Modifier.weight(1f),
                    onClick = { confirmationSheet = false; viewModel.confirmPhoto(item.id) },
                    label = { Text("保存为${item.displayName}") }) }
            } }
            Spacer(Modifier.height(24.dp))
        }
    }
    if (modelSheet) ModalBottomSheet(onDismissRequest = { modelSheet = false }, containerColor = MaterialTheme.colorScheme.background) {
        CloudModelChoices(state.cloudModels, state.cloudModelVersion, !state.capturing) { version ->
            viewModel.selectCloudModel(version); modelSheet = false
        }
        if (state.cloudModels.isEmpty()) {
            Text(state.cloudModelsError ?: "正在读取模型…", Modifier.padding(22.dp))
            TextButton(onClick = viewModel::refreshCloudModels, enabled = !state.cloudModelsLoading && !state.capturing,
                modifier = Modifier.padding(horizontal = 14.dp)) { Text("重新加载模型") }
        }
        Spacer(Modifier.windowInsetsBottomHeight(WindowInsets.navigationBars))
    }
    if (state.showCorrectionSheet) ModalBottomSheet(onDismissRequest = viewModel::dismissCorrection) {
        Column(Modifier.padding(22.dp)) {
            Text("选择正确类别", style = MaterialTheme.typography.headlineSmall)
            Text("保留原预测，追加人工修正。", style = MaterialTheme.typography.bodySmall)
            Spacer(Modifier.height(12.dp))
            catalog.categories.chunked(3).forEach { row -> Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                row.forEach { item -> AssistChip(onClick = { viewModel.applyCorrection(item.id, item.displayName) }, label = { Text(item.displayName) }) }
            } }
            Spacer(Modifier.height(24.dp))
        }
    }
}

@Composable
internal fun LiveRecognitionControl(enabled: Boolean, available: Boolean, version: String, onToggle: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth().padding(horizontal = 24.dp, vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text("实时观察", style = MaterialTheme.typography.titleSmall)
            Text("本地 $version · 拍照才保存记录", style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Switch(checked = enabled, onCheckedChange = onToggle, enabled = available,
            modifier = Modifier.testTag("live-recognition-toggle").semantics { contentDescription = "实时观察" })
    }
}

@Composable
internal fun LiveRecognitionOverlay(observation: LiveObservation?, active: Boolean, error: String?, displayName: (String) -> String) {
    Column(Modifier.fillMaxWidth().background(Color(0xEB183D32), RoundedCornerShape(16.dp))
        .testTag("live-recognition-overlay").padding(horizontal = 14.dp, vertical = 10.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("● 本地实时 · 试验提示", color = Color(0xFFD7EF78), style = MaterialTheme.typography.labelSmall,
                modifier = Modifier.weight(1f))
            Text("预览不保存", color = Color.White.copy(alpha = .7f), style = MaterialTheme.typography.labelSmall)
        }
        if (observation != null && active) {
            val scope = observation.prediction.scopeDecision
            val uncertain = scope?.needsConfirmation == true
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(if (uncertain) "暂不确定" else if (observation.stable) displayName(observation.prediction.label) else "正在确认…",
                    Modifier.weight(1f), color = Color.White, fontSize = 24.sp, fontWeight = FontWeight.Medium)
                Text("%.0f%%".format(observation.prediction.confidence * 100), color = Color.White,
                    style = MaterialTheme.typography.titleMedium)
            }
            Text(if (uncertain) "倾向${displayName(observation.prediction.label)} · ${scope!!.reason}"
                else if (observation.stable) "连续 3 帧一致 · 拍照可保存结果"
                else if (observation.lowConfidence) "倾向${displayName(observation.prediction.label)} · 请靠近一个主体"
                else "倾向${displayName(observation.prediction.label)} · ${observation.consecutive}/3 帧一致",
                color = Color.White.copy(alpha = .8f), style = MaterialTheme.typography.labelSmall)
        } else Text(error ?: if (active) "把一个主要物品放入画面，稍停片刻" else "实时观察已暂停",
            color = Color.White, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 6.dp))
    }
}

@Composable
internal fun PhotoConfirmationCard(candidate: PhotoConfirmation, enabled: Boolean, onConfirm: () -> Unit,
    onChoose: () -> Unit, onDiscard: () -> Unit) {
    val thumbnail by produceState<android.graphics.Bitmap?>(null, candidate.photoPath) {
        value = withContext(Dispatchers.IO) {
            candidate.photoPath?.let { path -> runCatching {
                com.mobilecloud.recognition.AppGraph.photoStore.decodeUpright(java.io.File(path), 512)
            }.getOrNull() }
        }
    }
    Surface(Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 16.dp).testTag("photo-confirmation"),
        shape = RoundedCornerShape(20.dp), color = MaterialTheme.colorScheme.surface,
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant)) {
        Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("范围提示 · 试验", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text("暂不确定", style = MaterialTheme.typography.headlineMedium)
            Text(candidate.prediction.scopeDecision?.reason ?: "请确认实际类别")
            thumbnail?.let { bitmap ->
                Image(bitmap.asImageBitmap(), contentDescription = "待确认的照片", contentScale = ContentScale.Fit,
                    modifier = Modifier.fillMaxWidth().height(140.dp).background(MaterialTheme.colorScheme.surfaceContainer))
            }
            Text("候选：${candidate.displayName} · %.1f%%".format(candidate.prediction.confidence * 100),
                style = MaterialTheme.typography.titleMedium)
            Text("照片已暂存，尚未生成记录。只凭分数不能保证判断出范围外物品。",
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Button(onClick = onConfirm, enabled = enabled, modifier = Modifier.fillMaxWidth().testTag("confirm-photo")) {
                Text("确认是${candidate.displayName}，保存记录")
            }
            OutlinedButton(onClick = onChoose, enabled = enabled, modifier = Modifier.fillMaxWidth()) { Text("选择其他类别并保存") }
            TextButton(onClick = onDiscard, enabled = enabled, modifier = Modifier.testTag("discard-photo")) { Text("不保存，重新拍摄") }
        }
    }
}

@Composable
internal fun CloudModelChoices(models: List<CloudModelOption>, selected: String?, enabled: Boolean, onSelect: (String) -> Unit) {
    Column(Modifier.fillMaxWidth().padding(horizontal = 22.dp, vertical = 12.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("选择云端模型", style = MaterialTheme.typography.headlineSmall)
        Text("只影响下一次云端识别，本地模型保持不变。", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        models.forEach { model ->
            val active = model.version == selected
            Surface(Modifier.fillMaxWidth().selectable(active, enabled && model.available, Role.RadioButton) { onSelect(model.version) }
                .testTag("cloud-model-" + model.version), shape = RoundedCornerShape(18.dp),
                color = if (active) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.surface,
                border = BorderStroke(1.dp, if (active) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.outlineVariant)) {
                val ink = if (active) MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.onSurface
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(model.displayName, Modifier.weight(1f), color = ink, style = MaterialTheme.typography.titleMedium)
                        Text(if (!model.available) "暂不可用" else if (active) "已选择 ✓" else "就绪", color = ink, style = MaterialTheme.typography.labelMedium)
                    }
                    Text(model.description, color = ink.copy(alpha = .8f), style = MaterialTheme.typography.bodySmall)
                    Text(model.version, color = ink.copy(alpha = .75f), style = MaterialTheme.typography.labelSmall)
                }
            }
        }
        Spacer(Modifier.height(12.dp))
    }
}

@Composable
internal fun InferenceModeSelector(mode: InferenceMode, enabled: Boolean, onSelect: (InferenceMode) -> Unit) {
    Row(Modifier.fillMaxWidth().padding(horizontal = 20.dp).background(MaterialTheme.colorScheme.surfaceContainer, RoundedCornerShape(20.dp)).padding(4.dp)) {
        InferenceMode.entries.forEach { item ->
            val selected = mode == item
            Column(Modifier.weight(1f).heightIn(min = 55.dp)
                .background(if (selected) MaterialTheme.colorScheme.primary else Color.Transparent, RoundedCornerShape(16.dp))
                .selectable(selected, enabled, Role.RadioButton) { onSelect(item) }.testTag("inference-mode-" + item.key)
                .padding(vertical = 8.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
                val ink = if (selected) MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.onSurface
                Text(item.title, color = ink, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
                Text(if (item == InferenceMode.DEVICE) "无需网络" else "可选择模型", color = ink.copy(alpha = .75f), style = MaterialTheme.typography.labelSmall)
            }
        }
    }
}

@Composable
private fun NoteChip(text: String) {
    Text(text, Modifier.background(MaterialTheme.colorScheme.primaryContainer, RoundedCornerShape(30.dp)).padding(horizontal = 12.dp, vertical = 7.dp),
        style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onPrimaryContainer)
}

@Composable
private fun ResultTicket(result: CaptureResult, onCorrect: () -> Unit) {
    Surface(Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 16.dp), shape = RoundedCornerShape(6.dp),
        color = MaterialTheme.colorScheme.surface, border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant)) {
        Column(Modifier.padding(20.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("本次观察", Modifier.weight(1f), style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                NoteChip(if (result.source == InferenceMode.CLOUD) "云端识别" else "本地识别")
            }
            Spacer(Modifier.height(20.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(result.correctedDisplayName ?: result.displayName, Modifier.weight(1f), fontSize = 36.sp, fontFamily = FontFamily.Serif)
                Column(horizontalAlignment = Alignment.End) {
                    Text("%.1f%%".format(result.prediction.confidence * 100), fontSize = 26.sp, fontWeight = FontWeight.Medium)
                    Text("原预测置信度", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            if (result.correctedDisplayName != null) Text("原预测：" + result.displayName, style = MaterialTheme.typography.bodySmall)
            if (result.manuallyConfirmed) Text("已由你确认并保存", color = MaterialTheme.colorScheme.primary)
            if (result.lowConfidence && result.correctedDisplayName == null && !result.manuallyConfirmed) Text("需要确认 · 置信度较低", color = MaterialTheme.colorScheme.error)
            val lineColor = MaterialTheme.colorScheme.outlineVariant
            Canvas(Modifier.fillMaxWidth().padding(vertical = 18.dp).height(1.dp)) {
                var x = 0f
                while (x < size.width) { drawLine(lineColor, androidx.compose.ui.geometry.Offset(x, 0f), androidx.compose.ui.geometry.Offset((x + 5.dp.toPx()).coerceAtMost(size.width), 0f)); x += 10.dp.toPx() }
            }
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(22.dp)) {
                Column(Modifier.weight(1f)) {
                    Text("计算耗时", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Text("${result.prediction.totalMs} ms", style = MaterialTheme.typography.titleMedium)
                }
                Column(Modifier.weight(1f)) {
                    Text(if (result.source == InferenceMode.CLOUD) "含网络总等待" else "识别来源", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Text(if (result.source == InferenceMode.CLOUD) "${result.elapsedMs} ms" else "这台设备", style = MaterialTheme.typography.titleMedium)
                }
            }
            Spacer(Modifier.height(14.dp))
            Text(result.prediction.modelVersion, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text("NO. " + result.recordId.take(8).uppercase(), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            TextButton(onClick = onCorrect, contentPadding = PaddingValues(vertical = 8.dp, horizontal = 0.dp)) { Text("结果不对？修正类别 ↗") }
        }
    }
}
