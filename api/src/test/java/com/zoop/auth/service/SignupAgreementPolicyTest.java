package com.zoop.auth.service;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;

import com.zoop.auth.dto.SignupRequest;
import com.zoop.auth.repository.SignupTermRow;
import com.zoop.auth.repository.SignupTermsRepository;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

class SignupAgreementPolicyTest {
    private static final Instant NOW = Instant.parse("2026-10-14T00:00:00Z");

    @Test
    void validatesCurrentVersionAndActualRequiredConsent() {
        var policy = policy(List.of(new SignupTermRow("service", true, "v2"),
                new SignupTermRow("privacy", true, "v3"),
                new SignupTermRow("marketing", false, "v1")));
        var accepted = List.of(new SignupRequest.Agreement("service", "v2", true),
                new SignupRequest.Agreement("privacy", "v3", true),
                new SignupRequest.Agreement("marketing", "v1", false));
        assertEquals(accepted, policy.validate(accepted, NOW));
        assertCode(ErrorCode.TERMS_REQUIRED, () -> policy.validate(accepted.subList(0, 1), NOW));
        assertCode(ErrorCode.TERMS_REQUIRED, () -> policy.validate(List.of(
                new SignupRequest.Agreement("service", "v1", true), accepted.get(1)), NOW));
        assertCode(ErrorCode.TERMS_REQUIRED, () -> policy.validate(List.of(
                new SignupRequest.Agreement("service", "v2", false), accepted.get(1)), NOW));
        assertCode(ErrorCode.INVALID_REQUEST, () -> policy.validate(List.of(
                accepted.get(0), accepted.get(0), accepted.get(1)), NOW));
        assertCode(ErrorCode.INVALID_REQUEST, () -> policy.validate(List.of(
                accepted.get(0), accepted.get(1),
                new SignupRequest.Agreement("unknown", "v1", true)), NOW));
    }

    @Test
    void missingApprovedVersionBlocksSignup() {
        var policy = policy(List.of(new SignupTermRow("service", true, null)));
        assertCode(ErrorCode.TERMS_REQUIRED, () -> policy.validate(List.of(), NOW));
        assertCode(ErrorCode.TERMS_REQUIRED, () -> policy(List.of()).validate(List.of(), NOW));
    }

    private static SignupAgreementPolicy policy(List<SignupTermRow> terms) {
        SignupTermsRepository repository = new SignupTermsRepository() {
            @Override
            public List<SignupTermRow> listCurrent(Instant at) {
                return new ArrayList<>(terms);
            }

            @Override
            public void recordAgreement(String memberId, String termId, String version,
                    boolean accepted, Instant at) {
            }
        };
        return new SignupAgreementPolicy(repository);
    }

    private static void assertCode(ErrorCode code, Runnable action) {
        assertEquals(code, assertThrows(CustomException.class, action::run).getErrorCode());
    }
}
