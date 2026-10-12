package com.oxphone.companion.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.oxphone.companion.CompanionViewModel

/** SPEC B: approve/deny pending privileged actions (jobs in
 *  `awaiting_approval`, e.g. non-public data routed to a remote worker). */
@Composable
fun ApprovalsScreen(vm: CompanionViewModel) {
    val state by vm.state.collectAsState()

    Column(Modifier.fillMaxSize().padding(16.dp),
           verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("Approvals", style = MaterialTheme.typography.headlineSmall)

        // The currently tracked job may itself be awaiting approval.
        val pending = state.pendingApprovals +
                listOfNotNull(state.currentJob)
                    .filter { it.status == "awaiting_approval" }

        if (pending.isEmpty()) {
            Text("No pending approvals.")
            return@Column
        }

        LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            items(pending, key = { it.job_id }) { job ->
                Card {
                    Column(Modifier.padding(12.dp),
                           verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text(job.task_type, style = MaterialTheme.typography.titleMedium)
                        Text("${job.job_id} • ${job.data_classification} → remote worker")
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            Button(onClick = { vm.approveJob(job.job_id) }) {
                                Text("Approve")
                            }
                            OutlinedButton(onClick = { vm.denyJob(job.job_id) }) {
                                Text("Deny")
                            }
                        }
                    }
                }
            }
        }
    }
}
