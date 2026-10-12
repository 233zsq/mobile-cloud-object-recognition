package com.mobilecloud.recognition.data.remote

import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.PATCH
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query
import retrofit2.http.Multipart
import retrofit2.http.Part
import okhttp3.MultipartBody
import okhttp3.RequestBody

/**
 * 云端接口定义：推理不写记录，成功结果由客户端经既有记录接口单独上报。
 * 接口实现就绪前的失败会保存在本地记录，不阻塞离线识别。
 */
interface ApiService {
    @Multipart
    @POST("api/infer")
    suspend fun infer(
        @Part("request_id") requestId: RequestBody,
        @Part("model_version") modelVersion: RequestBody,
        @Part image: MultipartBody.Part,
    ): retrofit2.Response<InferResponse>

    /** 新记录返回成功；相同 UUID 与相同内容返回已有记录；内容冲突不能覆盖（T08/T09） */
    @POST("api/records")
    suspend fun uploadRecord(@Body body: RecordUploadRequest): retrofit2.Response<Unit>

    /** 保留原预测；新修订更新人工标签；过期修订不能覆盖新标签（T10/T11） */
    @PATCH("api/records/{id}/label")
    suspend fun correctLabel(
        @Path("id") recordId: String,
        @Body body: CorrectionRequest,
    ): retrofit2.Response<Unit>

    /** 部署检查使用；设置页「测试连接」调用 */
    @GET("api/health")
    suspend fun health(@Query("client") client: String = "android"): HealthResponse

    @GET("api/categories")
    suspend fun categories(): CategoriesResponse

    @GET("api/records")
    suspend fun records(
        @Query("page") page: Int = 0,
        @Query("page_size") pageSize: Int = 20,
    ): retrofit2.Response<Unit>
}
