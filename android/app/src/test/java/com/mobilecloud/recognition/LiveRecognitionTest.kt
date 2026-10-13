package com.mobilecloud.recognition

import com.mobilecloud.recognition.inference.LiveRecognitionSession
import com.mobilecloud.recognition.inference.LiveResultTracker
import com.mobilecloud.recognition.inference.Prediction
import org.junit.Assert.*
import org.junit.Test

class LiveRecognitionTest {
    private fun prediction(label: String = "cup", confidence: Float = .9f, model: String = "v2") =
        Prediction(0, confidence, label, 5, 30, 35, model)

    @Test fun previewStartsOffAndNeverAdmitsOverlappingOrQueuedFrames() {
        val session = LiveRecognitionSession()
        assertNull(session.begin(0))
        session.setActive(true)
        val first = requireNotNull(session.begin(0))
        assertNull(session.begin(1000))
        assertTrue(session.finish(first, 100))
        assertNull(session.begin(499))
        assertNotNull(session.begin(500))
    }

    @Test fun pauseAndResumeInvalidateOldResultsWithoutStartingConcurrentInference() {
        val session = LiveRecognitionSession()
        session.setActive(true)
        val old = requireNotNull(session.begin(10))
        session.setActive(false)
        session.setActive(true)
        assertFalse(session.isCurrent(old))
        assertNull(session.begin(20))
        assertFalse(session.finish(old, 30))
        val next = requireNotNull(session.begin(30))
        assertFalse(session.finish(old, 40))
        assertTrue(session.isCurrent(next))
    }

    @Test fun slowFramesAreRateLimitedAndVeryOldResultsAreDiscarded() {
        val session = LiveRecognitionSession()
        session.setActive(true)
        val first = requireNotNull(session.begin(0))
        assertTrue(session.finish(first, 1000))
        assertNull(session.begin(1499))
        val next = requireNotNull(session.begin(1500))
        assertFalse(session.finish(next, 4100))
    }

    @Test fun threeConsistentFramesBecomeStableAndChangedSubjectImmediatelyClearsStability() {
        val tracker = LiveResultTracker()
        assertFalse(tracker.observe(prediction(), .5f, 0).stable)
        assertEquals(2, tracker.observe(prediction(), .5f, 500).consecutive)
        assertTrue(tracker.observe(prediction(), .5f, 1000).stable)
        val changed = tracker.observe(prediction("book"), .5f, 1500)
        assertFalse(changed.stable)
        assertEquals(1, changed.consecutive)
    }

    @Test fun lowConfidenceStaleFramesAndDifferentModelsCannotAccumulateStability() {
        val tracker = LiveResultTracker()
        tracker.observe(prediction(), .5f, 0)
        assertTrue(tracker.observe(prediction(confidence = .4f), .5f, 500).lowConfidence)
        assertEquals(1, tracker.observe(prediction(), .5f, 1000).consecutive)
        assertEquals(1, tracker.observe(prediction(), .5f, 4000).consecutive)
        assertEquals(1, tracker.observe(prediction(model = "v3"), .5f, 4500).consecutive)
        tracker.reset()
        assertEquals(1, tracker.observe(prediction(model = "v3"), .5f, 5000).consecutive)
    }
}
