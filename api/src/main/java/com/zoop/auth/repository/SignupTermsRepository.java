package com.zoop.auth.repository;

import java.time.Instant;
import java.util.List;

public interface SignupTermsRepository {
    List<SignupTermRow> listCurrent(Instant at);

    void recordAgreement(String memberId, String termId, String version,
            boolean accepted, Instant at);
}
