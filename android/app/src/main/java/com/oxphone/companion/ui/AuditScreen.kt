package com.oxphone.companion.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.oxphone.companion.CompanionViewModel
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** SPEC B: local view of the gateway's append-only audit history. */
@Composable
fun AuditScreen(vm: CompanionViewModel) {
    val state by vm.state.collectAsState()
    LaunchedEffect(Unit) { vm.refreshAudit() }

    Column(Modifier.fillMaxSize().padding(16.dp),
           verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text("Audit log", style = MaterialTheme.typography.headlineSmall)
            TextButton(onClick = { vm.refreshAudit() }) { Text("Refresh") }
        }

        LazyColumn(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            items(state.audit, key = { it.id }) { entry ->
                val ts = SimpleDateFormat("HH:mm:ss", Locale.US)
                    .format(Date((entry.ts * 1000).toLong()))
                ListItem(
                    headlineContent = { Text(entry.event) },
                    supportingContent = {
                        Text("${entry.job_id ?: "-"} • by ${entry.actor}")
                    },
                    overlineContent = { Text("#${entry.id} $ts") },
                )
                HorizontalDivider()
            }
        }
    }
}
