package com.oxphone.companion.ui

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.oxphone.companion.CompanionViewModel

/** SPEC B: live status, cancel button, result viewer. */
@Composable
fun JobStatusScreen(vm: CompanionViewModel) {
    val state by vm.state.collectAsState()
    val job = state.currentJob

    Column(Modifier.fillMaxSize().padding(16.dp),
           verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("Job status", style = MaterialTheme.typography.headlineSmall)

        if (job == null) {
            Text("No job submitted yet.")
            return@Column
        }

        AssistChip(onClick = {}, label = { Text(job.status) })
        Text("Job: ${job.job_id}")
        Text("Route: ${job.route ?: "-"}")
        Text("Classification: ${job.data_classification}")
        Text("Budget: ${job.spent_cents}/${job.budget_cents} cents spent")

        if (job.status in listOf("queued", "running", "awaiting_approval")) {
            Button(
                onClick = { vm.cancelJob(job.job_id) },
                colors = ButtonDefaults.buttonColors(
                    containerColor = MaterialTheme.colorScheme.error),
            ) { Text("Cancel") }
        }

        job.result?.let {
            Text("Result", style = MaterialTheme.typography.titleMedium)
            Surface(tonalElevation = 2.dp) {
                Text(it.toString(), Modifier.padding(12.dp))
            }
        }

        state.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
    }
}
