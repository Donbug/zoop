package com.zoop.admin.transcripts;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import com.zoop.admin.auth.service.AdminPrincipal;
import com.zoop.auth.service.CsrfKeyRing;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.NullAndEmptySource;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.SimpleTransactionStatus;
import tools.jackson.databind.json.JsonMapper;

class TranscriptServiceTest {
    private static final Instant NOW = Instant.parse("2026-11-03T00:00:00Z");
    private static final String ID = "synthetic-session";
    private static final AdminPrincipal ADMIN = new AdminPrincipal("allowed-admin", "operator@example.test", "운영자", "admin", "session");
    private static final TranscriptMasker.Owner OWNER = new TranscriptMasker.Owner("private-member", "owner@example.test", "합성회원");
    private final TranscriptReadPolicy policy = mock(TranscriptReadPolicy.class);
    private final TranscriptRepository repository = mock(TranscriptRepository.class);
    private final TranscriptAudit audit = mock(TranscriptAudit.class);
    private final TranscriptMasker masker = spy(new TranscriptMasker());
    private final JsonMapper mapper = JsonMapper.builder().build();
    private final CsrfKeyRing keys = new CsrfKeyRing("test", "test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA");
    private final PlatformTransactionManager transactions = mock(PlatformTransactionManager.class);
    private final TranscriptService service = service();

    private TranscriptService service() {
        when(transactions.getTransaction(any())).thenAnswer(call -> new SimpleTransactionStatus());
        return new TranscriptService(policy, repository, masker, audit, mapper, keys,
                Clock.fixed(NOW, ZoneOffset.UTC), transactions, new TranscriptPseudonym("", keys));
    }

    private void allow() { when(policy.allows(ADMIN)).thenReturn(true); }
    private void detailFixture() {
        allow();
        when(repository.find(ID)).thenReturn(Optional.of(new TranscriptRepository.Session(ID, OWNER, NOW)));
        when(repository.jobs(ID)).thenReturn(List.of(new TranscriptRepository.Job("synthetic-job", 1, NOW,
                "owner@example.test의 질문", "completed", "answered", "{\"answer\":\"010-2345-6789 답변\",\"citations\":[{}]}", null,
                "{\"items\":[{\"label\":\"합성 기업\"}]}")));
        when(repository.votes(ID)).thenReturn(List.of(new TranscriptRepository.Vote("synthetic-job", "down", "owner@example.test 사유")));
    }
    private static void code(ErrorCode expected, org.junit.jupiter.api.function.Executable action) {
        var error = assertThrows(CustomException.class, action);
        assertEquals(expected, error.getErrorCode());
        assertNull(error.getCause());
    }

    @Test void adminAllAloneCannotReadAndPermissionIsCheckedBeforePurposeOrRepository() {
        code(ErrorCode.ACCESS_DENIED, () -> service.detail(ADMIN, null, ID, "request"));
        verifyNoInteractions(repository, masker, transactions);
        verify(audit).record(eq(ADMIN), eq(ID), isNull(), eq("denied"), eq("request"), isNull(), isNull(), eq(0), eq(Map.of()));
    }

    @ParameterizedTest @NullAndEmptySource @ValueSource(strings={" ", "owner@example.test", "연락처 010-2345-6789", "검토\n목적", "\n품질 검토", "https://example.test", "token=secret"})
    void rejectsMissingOrSensitivePurposesWithoutSavingTheirOriginal(String purpose) {
        allow();
        code(ErrorCode.INVALID_REQUEST, () -> service.detail(ADMIN, purpose, ID, "request"));
        verifyNoInteractions(repository);
        verify(audit).record(eq(ADMIN), eq(ID), isNull(), eq("denied"), anyString(), isNull(), isNull(), eq(0), eq(Map.of()));
    }

    @Test void rejectsPurposeOverTwoHundredCharacters() {
        allow();
        code(ErrorCode.INVALID_REQUEST, () -> service.detail(ADMIN, "검".repeat(201), ID, "request"));
        verifyNoInteractions(repository);
    }

    @ParameterizedTest @ValueSource(strings={"2026-11-03", "2026.11.03", "2026/11/03", "20261103"})
    void acceptsAReportDateInThePurpose(String date) {
        detailFixture();
        service.detail(ADMIN, date + " 신고 건 확인", ID, "request");
        verify(audit).record(eq(ADMIN), eq(ID), eq(date + " 신고 건 확인"), eq("succeeded"), anyString(),
                isNull(), isNull(), eq(1), any());
    }

    @Test void returnsOnlyMaskedFieldsAndWritesTheAuditBeforeReturning() {
        detailFixture();
        var out = service.detail(ADMIN, "  응답 품질 검토  ", ID, "request");
        assertTrue(out.masking().completed());
        assertTrue(out.user().startsWith("user-"));
        assertEquals(Map.of("email", 2, "phone", 1), out.masking().counts());
        String wire = mapper.writeValueAsString(out);
        assertFalse(wire.contains(OWNER.id())); assertFalse(wire.contains(OWNER.email())); assertFalse(wire.contains("010-2345-6789"));
        assertEquals("answered", out.messages().getFirst().status());
        assertEquals(1, out.messages().getFirst().citationCount());
        var order = inOrder(policy, repository, transactions, masker, audit);
        order.verify(policy).allows(ADMIN); order.verify(repository).find(ID);
        order.verify(repository).jobs(ID); order.verify(repository).votes(ID);
        order.verify(transactions).commit(any());
        order.verify(masker, atLeastOnce()).mask(anyString(), eq(OWNER));
        order.verify(audit).record(eq(ADMIN), eq(ID), eq("응답 품질 검토"), eq("succeeded"), eq("request"),
                isNull(), isNull(), eq(1), eq(out.masking().counts()));
        verify(transactions).getTransaction(argThat(definition -> definition.isReadOnly()
                && definition.getIsolationLevel() == TransactionDefinition.ISOLATION_REPEATABLE_READ));
    }

    @Test void auditFailureNeverReturnsAMaskedOrRawBody() {
        detailFixture();
        doThrow(new IllegalStateException("private driver detail")).when(audit).record(any(),any(),any(),any(),any(),any(),any(),anyInt(),any());
        code(ErrorCode.AUDIT_UNAVAILABLE, () -> service.detail(ADMIN, "품질 검토", ID, "request"));
    }

    @Test void maskingFailureNeverFallsBackToOriginalAndIsAuditedAsFailed() {
        detailFixture();
        doThrow(new IllegalArgumentException("owner@example.test")).when(masker).mask(anyString(),any());
        code(ErrorCode.MASKING_FAILED, () -> service.detail(ADMIN, "품질 검토", ID, "request"));
        verify(audit).record(eq(ADMIN), eq(ID), eq("품질 검토"), eq("failed"), anyString(), isNull(),isNull(),eq(0),any());
    }

    @Test void rechecksPermissionOnEveryReadAndDoesNotUseACachedBody() {
        detailFixture();
        service.detail(ADMIN, "품질 검토", ID, "first");
        when(policy.allows(ADMIN)).thenReturn(false);
        code(ErrorCode.ACCESS_DENIED, () -> service.detail(ADMIN, "품질 검토", ID, "second"));
        verify(repository, times(1)).find(ID);
        verify(policy, times(2)).allows(ADMIN);
    }

    @Test void missingSessionIs404AndDoesNotSubstituteAnotherSession() {
        allow(); when(repository.find(ID)).thenReturn(Optional.empty());
        code(ErrorCode.RESOURCE_NOT_FOUND, () -> service.detail(ADMIN, "품질 검토", ID, "request"));
        verify(repository, never()).jobs(anyString());
    }

    @Test void alsoMasksFailedJobReasonsAndFrozenContextLabels() {
        detailFixture();
        when(repository.jobs(ID)).thenReturn(List.of(new TranscriptRepository.Job("synthetic-job", 1, NOW,
                "일반 질문", "failed", null, null,
                "{\"message\":\"owner@example.test 실패 사유\"}",
                "{\"items\":[{\"label\":\"010.2345.6789\"}]}")));
        var out = service.detail(ADMIN, "품질 검토", ID, "request");
        assertEquals("[이메일] 실패 사유", out.messages().getFirst().reason());
        assertEquals(List.of("[전화번호]"), out.messages().getFirst().contextLabels());
        assertEquals("", out.messages().getFirst().answer());
        assertEquals(0, out.messages().getFirst().citationCount());
        assertEquals(Map.of("email", 2, "phone", 1), out.masking().counts());
    }

    @ParameterizedTest @ValueSource(strings={"not-json", "[]", "{\"answer\":{\"raw\":\"owner@example.test\"}}"})
    void malformedStoredResultsFailClosedRatherThanReturningPartialMessages(String result) {
        detailFixture();
        when(repository.jobs(ID)).thenReturn(List.of(new TranscriptRepository.Job("synthetic-job", 1, NOW,
                "질문", "completed", "answered", result, null, "{}")));
        code(ErrorCode.MASKING_FAILED, () -> service.detail(ADMIN, "품질 검토", ID, "request"));
        verify(audit).record(eq(ADMIN), eq(ID), eq("품질 검토"), eq("failed"), anyString(), isNull(),isNull(),eq(0),any());
    }

    @Test void masksWholePreviewBeforeTruncationAndBindsCursorToAdminPurposeFilterAndLimit() {
        allow();
        var session = new TranscriptRepository.Session(ID, OWNER, NOW.minusSeconds(1));
        var row = new TranscriptRepository.Summary(session, NOW, 1, "질".repeat(115) + "owner@example.test", 0, 1);
        when(repository.total("disliked", NOW)).thenReturn(2L);
        when(repository.list(eq("disliked"), eq(NOW), any(), any(), eq(2))).thenReturn(List.of(row,row));
        var page = service.list(ADMIN, "품질 검토", "disliked", null, 1, "request");
        assertEquals(2, page.total()); assertNotNull(page.nextCursor());
        assertFalse(page.items().getFirst().preview().contains("owner@"));
        assertEquals(120, page.items().getFirst().preview().codePointCount(0,page.items().getFirst().preview().length()));
        code(ErrorCode.INVALID_CURSOR, () -> service.list(ADMIN, "다른 목적", "disliked", page.nextCursor(), 1, "request"));
        code(ErrorCode.INVALID_CURSOR, () -> service.list(ADMIN, "품질 검토", "all", page.nextCursor(), 1, "request"));
        code(ErrorCode.INVALID_CURSOR, () -> service.list(ADMIN, "품질 검토", "disliked", page.nextCursor(), 2, "request"));
        var another = new AdminPrincipal("another-admin", "operator2@example.test", "운영자2", "admin", "session2");
        when(policy.allows(another)).thenReturn(true);
        code(ErrorCode.INVALID_CURSOR, () -> service.list(another, "품질 검토", "disliked", page.nextCursor(), 1, "request"));
    }

    @Test void policyDefaultsToNobodyAndDoesNotChangeOtherAdminPermissions() {
        assertFalse(new TranscriptReadPolicy("").allows(ADMIN));
        assertTrue(new TranscriptReadPolicy(" someone, allowed-admin ").allows(ADMIN));
        assertFalse(new TranscriptReadPolicy("another-admin").allows(ADMIN));
        assertFalse(new TranscriptReadPolicy("allowed-admin").allows(new AdminPrincipal("allowed-admin", "", "", "unknown", "")));
    }
}
