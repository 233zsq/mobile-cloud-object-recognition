package com.mobilecloud.recognition.inference

/** Serial, rate-limited preview admission. In-flight work survives a pause only to release resources. */
class LiveRecognitionSession {
    data class Ticket(val generation: Long, val startedAt: Long)

    private var generation = 0L
    private var active = false
    private var inFlight: Ticket? = null
    private var nextFrameAt = 0L

    @Synchronized
    fun setActive(value: Boolean): Boolean {
        if (active == value) return false
        active = value
        generation++
        nextFrameAt = 0L
        return true
    }

    @Synchronized
    fun begin(now: Long): Ticket? {
        if (!active || inFlight != null || now < nextFrameAt) return null
        return Ticket(generation, now).also { inFlight = it }
    }

    @Synchronized
    fun isCurrent(ticket: Ticket): Boolean = active && ticket.generation == generation && inFlight == ticket

    @Synchronized
    fun finish(ticket: Ticket, now: Long): Boolean {
        if (inFlight != ticket) return false
        inFlight = null
        val current = active && ticket.generation == generation
        // Fast devices run at <=2 Hz; slow devices rest for half their processing time.
        if (current) nextFrameAt = maxOf(ticket.startedAt + 500L, now + (now - ticket.startedAt).coerceAtLeast(0L) / 2)
        return current && now - ticket.startedAt <= LiveResultTracker.FRESHNESS_MS
    }
}

data class LiveObservation(
    val prediction: Prediction,
    val consecutive: Int,
    val lowConfidence: Boolean,
    val observedAt: Long,
) {
    val stable: Boolean get() = !lowConfidence && prediction.scopeDecision?.needsConfirmation != true && consecutive >= 3
}

/** Temporal smoothing only; this does not detect objects outside the model's ten classes. */
class LiveResultTracker {
    private var last: LiveObservation? = null

    fun reset() { last = null }

    fun observe(prediction: Prediction, threshold: Float, now: Long): LiveObservation {
        val lowConfidence = prediction.isLowConfidence(threshold)
        val previous = last
        val same = previous != null && now - previous.observedAt in 0..FRESHNESS_MS &&
            previous.prediction.label == prediction.label && previous.prediction.modelVersion == prediction.modelVersion &&
            !previous.lowConfidence && !lowConfidence && previous.prediction.scopeDecision?.needsConfirmation != true &&
            prediction.scopeDecision?.needsConfirmation != true
        return LiveObservation(prediction, if (same) (previous!!.consecutive + 1).coerceAtMost(3) else 1,
            lowConfidence, now).also { last = it }
    }

    companion object { const val FRESHNESS_MS = 2_500L }
}
