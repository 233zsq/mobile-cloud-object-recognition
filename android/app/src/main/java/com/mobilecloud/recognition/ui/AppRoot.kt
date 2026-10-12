package com.mobilecloud.recognition.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.Alignment
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.dp
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Icon
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.List
import androidx.compose.material.icons.filled.Settings
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import com.mobilecloud.recognition.AppGraph
import com.mobilecloud.recognition.R
import com.mobilecloud.recognition.ui.capture.CaptureScreen
import com.mobilecloud.recognition.ui.records.RecordsScreen
import com.mobilecloud.recognition.ui.settings.SettingsScreen
import com.mobilecloud.recognition.ui.settings.SettingsPage
import com.mobilecloud.recognition.ui.settings.SettingsViewModel
import androidx.lifecycle.viewmodel.compose.viewModel

private data class TopRoute(val route: String, val label: String)

private val CAPTURE = TopRoute("capture", "识别")
private val RECORDS = TopRoute("records", "记录")
private val SETTINGS = TopRoute("settings", "我的")

/** 底部三 Tab：采集 / 记录 / 设置 */
@Composable
fun AppRoot() {
    val navController = rememberNavController()
    val backStackEntry by navController.currentBackStackEntryAsState()
    val currentRoute = backStackEntry?.destination?.route

    LaunchedEffect(Unit) {
        AppGraph.syncScheduler.requestSync()
    }

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        bottomBar = {
            if (currentRoute?.startsWith("settings/") != true) {
                Row(Modifier.fillMaxWidth().navigationBarsPadding().padding(horizontal = 20.dp, vertical = 10.dp)
                    .background(MaterialTheme.colorScheme.primary, RoundedCornerShape(28.dp)).padding(6.dp)) {
                    listOf(CAPTURE, RECORDS, SETTINGS).forEach { tab ->
                        val selected = currentRoute == tab.route
                        Column(
                            modifier = Modifier.weight(1f).background(if (selected) MaterialTheme.colorScheme.primaryContainer else Color.Transparent,
                                RoundedCornerShape(23.dp)).heightIn(min = 52.dp).selectable(selected, role = Role.Tab, onClick = {
                                navController.navigate(tab.route) {
                                    popUpTo(navController.graph.findStartDestination().id) {
                                        saveState = true
                                    }
                                    launchSingleTop = true
                                    restoreState = true
                                }
                            }).padding(vertical = 6.dp),
                            horizontalAlignment = Alignment.CenterHorizontally,
                        ) {
                            val ink = if (selected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onPrimary
                            Box(Modifier.padding(vertical = 1.dp)) { TabIcon(tab.route, ink) }
                            Text(tab.label, style = MaterialTheme.typography.labelMedium, color = ink)
                        }
                    }
                }
            }
        },
    ) { padding ->
        NavHost(
            navController = navController,
            startDestination = CAPTURE.route,
            modifier = Modifier.padding(padding).consumeWindowInsets(padding),
        ) {
            composable(CAPTURE.route) { CaptureScreen(catalog = AppGraph.categoryCatalog) }
            composable(RECORDS.route) { RecordsScreen() }
            composable(SETTINGS.route) {
                SettingsScreen(onOpenPage = { page -> navController.navigate("settings/${page.path}") })
            }
            SettingsPage.entries.filter { it != SettingsPage.OVERVIEW }.forEach { page ->
                composable("settings/${page.path}") { entry ->
                    val owner = remember(entry) { navController.getBackStackEntry(SETTINGS.route) }
                    val settingsViewModel: SettingsViewModel = viewModel(viewModelStoreOwner = owner)
                    SettingsScreen(viewModel = settingsViewModel, page = page, onBack = { navController.popBackStack() })
                }
            }
        }
    }
}

@Composable
private fun TabIcon(route: String, tint: Color) {
    when (route) {
        CAPTURE.route -> Icon(painterResource(R.drawable.ic_tab_camera), contentDescription = null, tint = tint)
        RECORDS.route -> Icon(Icons.Filled.List, contentDescription = null, tint = tint)
        SETTINGS.route -> Icon(Icons.Filled.Settings, contentDescription = null, tint = tint)
    }
}
