package com.zoop.auth.repository;

import java.time.Instant;
import java.util.List;

public interface AuthRateEventStore {
    void lock(String scope, String subjectHash);

    List<Instant> recent(String scope, String subjectHash, Instant after, int limit);

    void add(String scope, String subjectHash, Instant at);

    void clear(String scope, String subjectHash);

    void purgeBefore(Instant before);
}
