package com.zoop.auth.service;

import java.time.Instant;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

import com.zoop.auth.dto.SignupRequest;
import com.zoop.auth.repository.JdbcSignupTermsRepository;
import com.zoop.auth.repository.SignupTermRow;
import com.zoop.auth.repository.SignupTermsRepository;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import org.springframework.context.annotation.Import;
import org.springframework.jdbc.core.JdbcTemplate;

import static org.junit.jupiter.api.Assertions.*;

@SpringBootTest(properties = {
        "ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test",
        "ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
})
@Import(SignupRollbackPostgresTest.FailingAgreementConfig.class)
@EnabledIfEnvironmentVariable(named = "DB_URL", matches = "jdbc:postgresql:.*")
class SignupRollbackPostgresTest {
    @Autowired SignupService signups;
    @Autowired JdbcSignupTermsRepository actualTerms;
    @Autowired JdbcTemplate jdbc;
    @Autowired AtomicReference<String> attemptedMemberId;

    @Test
    void agreementWriteFailureRollsBackMemberAndSession() {
        String email = "rollback-" + UUID.randomUUID() + "@example.com";
        List<SignupRequest.Agreement> agreements = actualTerms.listCurrent(Instant.now()).stream()
                .filter(term -> term.required() && term.version() != null)
                .map(term -> new SignupRequest.Agreement(term.id(), term.version(), true)).toList();
        assertEquals(2, agreements.size());
        var request = new SignupRequest(email, "correct horse battery staple 2026", "Rollback Member", agreements);
        try {
            assertThrows(IllegalStateException.class,
                    () -> signups.signup(request, EmailAddress.parse(email), null, "rollback-test"));
            assertEquals(0, jdbc.queryForObject(
                    "SELECT count(*) FROM members WHERE email_key = ?", Integer.class, email));
            assertNotNull(attemptedMemberId.get());
            assertEquals(0, jdbc.queryForObject("SELECT count(*) FROM term_agreements WHERE member_id = ?",
                    Integer.class, attemptedMemberId.get()));
            assertEquals(0, jdbc.queryForObject("SELECT count(*) FROM member_sessions WHERE member_id = ?",
                    Integer.class, attemptedMemberId.get()));
        } finally {
            jdbc.update("DELETE FROM term_agreements WHERE member_id IN (SELECT id FROM members WHERE email_key = ?)", email);
            jdbc.update("DELETE FROM member_sessions WHERE member_id IN (SELECT id FROM members WHERE email_key = ?)", email);
            jdbc.update("DELETE FROM members WHERE email_key = ?", email);
        }
    }

    @TestConfiguration
    static class FailingAgreementConfig {
        @Bean
        AtomicReference<String> attemptedMemberId() {
            return new AtomicReference<>();
        }

        @Bean
        @Primary
        SignupTermsRepository failingSignupTermsRepository(JdbcSignupTermsRepository delegate,
                AtomicReference<String> attemptedMemberId) {
            AtomicInteger writes = new AtomicInteger();
            return new SignupTermsRepository() {
                @Override
                public List<SignupTermRow> listCurrent(Instant at) {
                    return delegate.listCurrent(at);
                }

                @Override
                public void recordAgreement(String memberId, String termId, String version,
                        boolean accepted, Instant at) {
                    attemptedMemberId.set(memberId);
                    if (writes.incrementAndGet() == 2) {
                        throw new IllegalStateException("simulated agreement write failure");
                    }
                    delegate.recordAgreement(memberId, termId, version, accepted, at);
                }
            };
        }
    }
}
