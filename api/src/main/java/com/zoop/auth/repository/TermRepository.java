package com.zoop.auth.repository;

import java.time.Instant;
import java.util.List;

public interface TermRepository {
    List<TermRow> listAt(Instant asOf, String afterId, Long fetchCount);
}
