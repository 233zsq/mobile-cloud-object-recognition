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

    @Query("UPDATE records SET correctionPending = 0, lastError = NULL, updatedAt = :now WHERE recordId = :recordId")
    suspend fun markCorrectionSynced(recordId: String, now: Long)

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
}
