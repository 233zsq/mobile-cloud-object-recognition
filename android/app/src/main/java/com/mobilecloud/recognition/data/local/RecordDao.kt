package com.mobilecloud.recognition.data.local

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

@Dao
interface RecordDao {

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(record: RecordEntity)

    @Query("SELECT * FROM records WHERE recordId = :recordId")
    suspend fun byId(recordId: String): RecordEntity?

    @Query("SELECT * FROM records ORDER BY capturedAt DESC")
    fun observeAll(): Flow<List<RecordEntity>>

    @Query("SELECT COUNT(*) FROM records")
    fun observeTotal(): Flow<Int>

    @Query("SELECT COUNT(*) FROM records WHERE uploaded = 0 OR correctionPending = 1")
    fun observePendingCount(): Flow<Int>

    @Query("SELECT * FROM records WHERE uploaded = 0 ORDER BY capturedAt ASC")
    suspend fun pendingUploads(): List<RecordEntity>

    @Query("SELECT * FROM records WHERE uploaded = 1 AND correctionPending = 1 ORDER BY correctedAt ASC")
    suspend fun pendingCorrections(): List<RecordEntity>

    @Query("UPDATE records SET uploaded = 1, lastError = NULL, updatedAt = :now WHERE recordId = :recordId")
    suspend fun markUploaded(recordId: String, now: Long)

    /** 仅当本地修订号仍等于已发送修订号时清除待同步标志，避免在途请求掩盖更新的修订（T11 竞态） */
    @Query(
        "UPDATE records SET correctionPending = 0, lastError = NULL, updatedAt = :now " +
            "WHERE recordId = :recordId AND revision = :revision"
    )
    suspend fun markCorrectionSynced(recordId: String, revision: Int, now: Long)

    @Query("UPDATE records SET lastError = :error, updatedAt = :now WHERE recordId = :recordId")
    suspend fun markError(recordId: String, error: String, now: Long)

    @Query(
        "UPDATE records SET correctedIndex = :correctedIndex, correctedLabel = :correctedLabel, " +
            "revision = revision + 1, correctedAt = :correctedAt, correctionPending = 1, updatedAt = :now " +
            "WHERE recordId = :recordId"
    )
    suspend fun applyCorrection(
        recordId: String,
        correctedIndex: Int,
        correctedLabel: String,
        correctedAt: Long,
        now: Long,
    )

    /** 本地删除单条记录（仅本机；云端无删除接口，已入库记录在服务端保留） */
    @Query("DELETE FROM records WHERE recordId = :recordId")
    suspend fun delete(recordId: String)

    /** 清空前的照片路径快照：先取路径再删行，随后逐个删除文件 */
    @Query("SELECT photoPath FROM records WHERE photoPath IS NOT NULL")
    suspend fun allPhotoPaths(): List<String>

    @Query("SELECT COUNT(*) FROM records")
    suspend fun count(): Int

    @Query("SELECT COUNT(*) FROM records WHERE uploaded = 0 OR correctionPending = 1")
    suspend fun pendingCount(): Int

    /** 清空全部本地记录（仅本机；云端已入库数据保留） */
    @Query("DELETE FROM records")
    suspend fun deleteAll()
}
