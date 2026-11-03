package com.zoop.admin.transcripts;

import java.time.Instant;
import java.util.List;
import java.util.Optional;

public interface TranscriptRepository {
    record Session(String id, TranscriptMasker.Owner owner, Instant startedAt) { }
    record Summary(Session session, Instant lastAt, int messages, String preview, long up, long down) { }
    record Job(String id, int seq, Instant at, String question, String status, String outcome,
            String result, String failure, String context) { }
    record Vote(String jobId, String value, String reason) { }

    long total(String only, Instant asOf);
    List<Summary> list(String only, Instant asOf, Instant beforeAt, String beforeId, int limit);
    Optional<Session> find(String sessionId);
    List<Job> jobs(String sessionId);
    List<Vote> votes(String sessionId);
}
