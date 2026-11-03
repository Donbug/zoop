package com.zoop.admin.transcripts;

import java.time.Instant;
import java.util.List;
import java.util.Map;

/** FS066-03 / listMaskedTranscripts · getMaskedTranscript, no raw owner identity. */
public final class TranscriptHttpSchemas {
    private TranscriptHttpSchemas() { }
    public record Page(List<Summary> items, String nextCursor, long total) { }
    public record Summary(String id, String user, String userKind, Instant startedAt, Instant lastAt,
            int messages, String preview, long up, long down) { }
    public record Detail(String id, String user, String userKind, Instant startedAt, List<Message> messages,
            Masking masking) { }
    public record Message(String id, int seq, Instant at, String question, String answer, String status,
            String reason, List<String> contextLabels, int citationCount, Feedback feedback) { }
    public record Feedback(long up, long down, List<String> reasons) { }
    public record Masking(boolean completed, List<String> rules, Map<String, Integer> counts) { }
}
