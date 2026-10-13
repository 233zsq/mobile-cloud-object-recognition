package com.mobilecloud.recognition

import android.database.sqlite.SQLiteDatabase
import androidx.room.Room
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.mobilecloud.recognition.data.local.AppDatabase
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class RecordMigrationTest {
    @Test fun versionOneRecordsKeepTheirPredictionCorrectionAndSyncState() = runBlocking {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val name = "migration-fixture.db"
        context.deleteDatabase(name)
        val schema = JSONObject(instrumentation.context.assets.open("records-schema-v1.json").bufferedReader().use { it.readText() })
            .getJSONObject("database").getJSONArray("entities").getJSONObject(0).getString("createSql")
            .replace("$" + "{TABLE_NAME}", "records")
        val file = context.getDatabasePath(name).apply { parentFile!!.mkdirs() }
        SQLiteDatabase.openOrCreateDatabase(file, null).use { db ->
            db.execSQL(schema)
            db.execSQL("INSERT INTO records (recordId,clientId,modelVersion,predictedIndex,predictedLabel,confidence,latencyMs,capturedAt,revision,correctedIndex,correctedLabel,uploaded,correctionPending,updatedAt) VALUES ('legacy','fixture','campus-gpu-v1',0,'cup',0.9,25,100,2,2,'book',1,1,200)")
            db.version = 1
        }
        val db = Room.databaseBuilder(context, AppDatabase::class.java, name)
            .addMigrations(AppDatabase.MIGRATION_1_2, AppDatabase.MIGRATION_2_3).build()
        try {
            val record = db.recordDao().observeAll().first().single()
            assertEquals("device", record.inferenceSource)
            assertEquals("cup", record.predictedLabel)
            assertEquals("book", record.correctedLabel)
            assertEquals(2, record.revision)
            assertTrue(record.uploaded)
            assertTrue(record.correctionPending)
            assertNull(record.scopeDecisionJson)
            db.recordDao().insert(record.copy(recordId = "cloud-fixture", inferenceSource = "cloud"))
            assertEquals("cloud", db.recordDao().observeAll().first().first { it.recordId == "cloud-fixture" }.inferenceSource)
        } finally { db.close(); context.deleteDatabase(name) }
    }
}
