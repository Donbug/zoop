package com.zoop.admin.transcripts;

import io.swagger.v3.oas.annotations.media.Schema;
import java.time.Instant;
import java.util.List;
import java.util.Map;

/** FS066-03 / listMaskedTranscripts · getMaskedTranscript, no raw owner identity. */
public final class TranscriptHttpSchemas {
    private TranscriptHttpSchemas() { }
    @Schema(name = "TranscriptPage", requiredProperties = {"items", "nextCursor", "total"})
    public record Page(List<Summary> items, @Schema(nullable = true) String nextCursor, long total) { }
    @Schema(name = "TranscriptSummary", requiredProperties = {"id", "user", "userKind", "startedAt", "lastAt", "messages", "preview", "up", "down"})
    public record Summary(String id, String user, @Schema(allowableValues = {"member", "guest"}) String userKind, Instant startedAt, Instant lastAt,
            int messages, String preview, long up, long down) { }
    @Schema(name = "TranscriptDetail", requiredProperties = {"id", "user", "userKind", "startedAt", "messages", "masking"})
    public record Detail(String id, String user, @Schema(allowableValues = {"member", "guest"}) String userKind, Instant startedAt, List<Message> messages,
            Masking masking) { }
    @Schema(name = "TranscriptMessage", requiredProperties = {"id", "seq", "at", "question", "answer", "status", "reason", "contextLabels", "citationCount", "feedback"})
    public record Message(String id, int seq, Instant at, String question, String answer, String status,
            @Schema(nullable = true) String reason, List<String> contextLabels, int citationCount, Feedback feedback) { }
    @Schema(name = "TranscriptFeedback", requiredProperties = {"up", "down", "reasons"})
    public record Feedback(long up, long down, List<String> reasons) { }
    @Schema(name = "MaskingReport", requiredProperties = {"completed", "rules", "counts"})
    public record Masking(boolean completed, List<String> rules, Map<String, Integer> counts) { }
}
