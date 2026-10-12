package com.oxphone.companion

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.oxphone.companion.net.AuditEntry
import com.oxphone.companion.net.GatewayApi
import com.oxphone.companion.net.JobStatusResponse
import com.oxphone.companion.net.JobSubmit
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

/** Shared state for the companion screens. Talks to the gateway via
 *  [GatewayApi]; "Hermes requests, the OS decides" — this app only ever
 *  submits and observes. */
class CompanionViewModel(
    private val api: GatewayApi,
    private val adminToken: String,
) : ViewModel() {

    data class UiState(
        val submitting: Boolean = false,
        val error: String? = null,
        val currentJob: JobStatusResponse? = null,
        val pendingApprovals: List<JobStatusResponse> = emptyList(),
        val audit: List<AuditEntry> = emptyList(),
    )

    private val _state = MutableStateFlow(UiState())
    val state: StateFlow<UiState> = _state

    fun submitTask(
        taskText: String,
        classification: String,
        capabilities: List<String>,
        budgetCents: Int,
    ) {
        viewModelScope.launch {
            _state.value = _state.value.copy(submitting = true, error = null)
            try {
                val res = api.submitJob(
                    JobSubmit(
                        task_type = "freeform",
                        payload_ref = taskText,
                        data_classification = classification,
                        requested_capabilities = capabilities,
                        budget_cents = budgetCents,
                        deadline_s = 3600,
                    )
                )
                pollJob(res.job_id)
            } catch (e: Exception) {
                _state.value = _state.value.copy(submitting = false, error = e.message)
            }
        }
    }

    /** Poll job status until it reaches a terminal state. */
    fun pollJob(jobId: String) {
        viewModelScope.launch {
            while (true) {
                try {
                    val job = api.getJob(jobId)
                    _state.value = _state.value.copy(submitting = false, currentJob = job)
                    if (job.status in listOf("completed", "failed", "cancelled")) return@launch
                } catch (e: Exception) {
                    _state.value = _state.value.copy(submitting = false, error = e.message)
                    return@launch
                }
                delay(1000)
            }
        }
    }

    fun cancelJob(jobId: String) {
        viewModelScope.launch {
            try {
                api.cancelJob(jobId)
                _state.value = _state.value.copy(
                    currentJob = _state.value.currentJob?.copy(status = "cancelled"))
            } catch (e: Exception) {
                _state.value = _state.value.copy(error = e.message)
            }
        }
    }

    fun approveJob(jobId: String) {
        viewModelScope.launch {
            try {
                api.approveJob(jobId)
                _state.value = _state.value.copy(
                    pendingApprovals = _state.value.pendingApprovals
                        .filterNot { it.job_id == jobId })
            } catch (e: Exception) {
                _state.value = _state.value.copy(error = e.message)
            }
        }
    }

    fun denyJob(jobId: String) = cancelJob(jobId)

    fun refreshAudit() {
        viewModelScope.launch {
            try {
                _state.value = _state.value.copy(audit = api.getAudit(adminToken))
            } catch (e: Exception) {
                _state.value = _state.value.copy(error = e.message)
            }
        }
    }
}
