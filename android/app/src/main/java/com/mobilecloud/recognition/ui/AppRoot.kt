package com.mobilecloud.recognition.ui

import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.List
import androidx.compose.material.icons.filled.Settings
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
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

private data class TopRoute(val route: String, val label: String)

private val CAPTURE = TopRoute("capture", "采集")
private val RECORDS = TopRoute("records", "记录")
private val SETTINGS = TopRoute("settings", "设置")

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
        bottomBar = {
            NavigationBar {
                listOf(CAPTURE, RECORDS, SETTINGS).forEach { tab ->
                    val selected = currentRoute == tab.route
                    NavigationBarItem(
                        selected = selected,
                        onClick = {
                            navController.navigate(tab.route) {
                                popUpTo(navController.graph.findStartDestination().id) {
                                    saveState = true
                                }
                                launchSingleTop = true
                                restoreState = true
                            }
                        },
                        icon = { TabIcon(tab.route) },
                        label = { Text(tab.label) },
                    )
                }
            }
        },
    ) { padding ->
        NavHost(
            navController = navController,
            startDestination = CAPTURE.route,
            modifier = Modifier.padding(padding),
        ) {
            composable(CAPTURE.route) { CaptureScreen(catalog = AppGraph.categoryCatalog) }
            composable(RECORDS.route) { RecordsScreen() }
            composable(SETTINGS.route) { SettingsScreen() }
        }
    }
}

@Composable
private fun TabIcon(route: String) {
    when (route) {
        CAPTURE.route -> Icon(painterResource(R.drawable.ic_tab_camera), contentDescription = "采集")
        RECORDS.route -> Icon(Icons.Filled.List, contentDescription = "记录")
        SETTINGS.route -> Icon(Icons.Filled.Settings, contentDescription = "设置")
    }
}
