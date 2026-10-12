package com.oxphone.companion

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.oxphone.companion.net.GatewayClient
import com.oxphone.companion.ui.ApprovalsScreen
import com.oxphone.companion.ui.AuditScreen
import com.oxphone.companion.ui.JobStatusScreen
import com.oxphone.companion.ui.TaskSubmitScreen

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Emulator → host loopback. Admin token never ships in code in real
        // builds; here it is read from BuildConfig/local.properties at build
        // time. Prototype default matches a local dev gateway.
        val baseUrl = "http://10.0.2.2:8000/"
        val adminToken = BuildConfig.GATEWAY_ADMIN_TOKEN
        val api = GatewayClient.create(baseUrl)

        setContent {
            MaterialTheme {
                val vm: CompanionViewModel = viewModel(factory =
                    object : ViewModelProvider.Factory {
                        @Suppress("UNCHECKED_CAST")
                        override fun <T : ViewModel> create(modelClass: Class<T>): T =
                            CompanionViewModel(api, adminToken) as T
                    })
                CompanionApp(vm)
            }
        }
    }
}

@Composable
fun CompanionApp(vm: CompanionViewModel) {
    val nav = rememberNavController()
    val tabs = listOf("submit", "status", "approvals", "audit")
    var tab by remember { mutableStateOf(tabs.first()) }

    Scaffold(
        bottomBar = {
            NavigationBar {
                tabs.forEach { t ->
                    NavigationBarItem(
                        selected = tab == t,
                        onClick = { tab = t; nav.navigate(t) { launchSingleTop = true } },
                        icon = {},
                        label = { Text(t.replaceFirstChar { it.uppercase() }) },
                    )
                }
            }
        }
    ) { padding ->
        NavHost(nav, startDestination = "submit",
                modifier = Modifier.padding(padding)) {
            composable("submit") {
                TaskSubmitScreen(vm, onSubmitted = {
                    tab = "status"
                    nav.navigate("status") { launchSingleTop = true }
                })
            }
            composable("status") { JobStatusScreen(vm) }
            composable("approvals") { ApprovalsScreen(vm) }
            composable("audit") { AuditScreen(vm) }
        }
    }
}
