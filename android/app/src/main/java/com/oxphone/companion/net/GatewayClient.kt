package com.oxphone.companion.net

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement
import okhttp3.OkHttpClient
import retrofit2.Retrofit
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.converter.kotlinx.serialization.asConverterFactory
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType

/**
 * Client mirroring the gateway API 1:1 (SPEC section A / Contracts).
 * Field names match gateway/models.py exactly.
 */

enum class Classification { public, internal, confidential, secret }

enum class JobStatus {
    queued, running, awaiting_approval, completed, failed, cancelled
}

enum class Route { `on-device`, local_worker, remote_worker, paid_model }

@Serializable
data class JobSubmit(
    val task_type: String,
    val payload_ref: String,
    val data_classification: String,
    val requested_capabilities: List<String>,
    val budget_cents: Int,
    val deadline_s: Int,
)

@Serializable
data class JobSubmitResponse(
    val job_id: String,
    val status: String,
    val route: String? = null,
)

@Serializable
data class JobStatusResponse(
    val job_id: String,
    val status: String,
    val route: String? = null,
    val task_type: String,
    val data_classification: String,
    val requested_capabilities: List<String>,
    val budget_cents: Int,
    val spent_cents: Int,
    val deadline_s: Int,
    val worker_id: String? = null,
    val result: JsonElement? = null,
    val created_at: Double,
)

@Serializable
data class JobCancelResponse(val job_id: String, val status: String)

@Serializable
data class JobApproveResponse(
    val job_id: String,
    val status: String,
    val route: String? = null,
)

@Serializable
data class WorkerRegister(
    val worker_id: String? = null,
    val capabilities: List<String>,
    val route_type: String, // "local" | "remote"
    val free: Boolean = true,
)

@Serializable
data class WorkerRegisterResponse(
    val worker_id: String,
    val token: String,
    val capabilities: List<String>,
    val route_type: String,
    val free: Boolean,
)

@Serializable
data class JobClaim(
    val worker_token: String,
    val idempotency_key: String,
)

@Serializable
data class JobClaimResponse(
    val job_id: String,
    val claim_id: String,
    val worker_id: String,
    val status: String,
    val idempotency_key: String,
)

@Serializable
data class JobComplete(
    val worker_token: String,
    val result: JsonElement? = null,
)

@Serializable
data class AuditEntry(
    val id: Int,
    val ts: Double,
    val event: String,
    val job_id: String? = null,
    val actor: String,
    val detail: Map<String, JsonElement> = emptyMap(),
)

interface GatewayApi {
    @POST("/jobs")
    suspend fun submitJob(@Body body: JobSubmit): JobSubmitResponse

    @GET("/jobs/{id}")
    suspend fun getJob(@Path("id") id: String): JobStatusResponse

    @POST("/jobs/{id}/cancel")
    suspend fun cancelJob(@Path("id") id: String): JobCancelResponse

    @POST("/jobs/{id}/approve")
    suspend fun approveJob(@Path("id") id: String): JobApproveResponse

    @POST("/jobs/{id}/claim")
    suspend fun claimJob(@Path("id") id: String, @Body body: JobClaim): JobClaimResponse

    @POST("/jobs/{id}/complete")
    suspend fun completeJob(@Path("id") id: String, @Body body: JobComplete): JobStatusResponse

    @POST("/workers/register")
    suspend fun registerWorker(
        @Body body: WorkerRegister,
        @Header("X-Admin-Token") adminToken: String,
    ): WorkerRegisterResponse

    @POST("/workers/{id}/revoke")
    suspend fun revokeWorker(
        @Path("id") id: String,
        @Header("X-Admin-Token") adminToken: String,
    ): WorkerRegisterResponse

    @GET("/audit")
    suspend fun getAudit(@Header("X-Admin-Token") adminToken: String): List<AuditEntry>
}

object GatewayClient {
    /**
     * @param baseUrl e.g. "http://10.0.2.2:8000/" (emulator → host loopback).
     */
    fun create(baseUrl: String): GatewayApi {
        val json = Json { ignoreUnknownKeys = true }
        val client = OkHttpClient.Builder().build()
        return Retrofit.Builder()
            .baseUrl(baseUrl)
            .client(client)
            .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
            .build()
            .create(GatewayApi::class.java)
    }
}
