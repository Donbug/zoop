package com.zoop.admin.audit;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;

import com.zoop.auth.service.CsrfKeyRing;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import tools.jackson.databind.json.JsonMapper;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class AdminAuditQueryServiceTest {
    private static final Instant NOW = Instant.parse("2026-10-21T09:00:00Z");

    @Mock AdminAuditReadRepository repository;

    @Test
    void convertsExistingRowsAndExposesOnlyAllowedDetail() {
        when(repository.page(any(), any(), any(), any(), any(), any(), any(), anyInt()))
                .thenReturn(List.of(
                        row(3, "anonymous", "auth.login_failed", "denied",
                                "invalid_credentials", "{\"password\":\"secret\"}"),
                        row(2, "admin", "member.block", "succeeded",
                                "policy violation", "{\"beforeStatus\":\"active\",\"afterStatus\":\"blocked\","
                                        + "\"beforeRevision\":1,\"afterRevision\":2,\"token\":\"secret\"}"),
                        row(1, "admin", "member.unblock", "succeeded",
                                "secret@example.com", "{\"unknown\":\"private\"}")));

        var page = service().list("admin-1", null, null, null, null, null, null);

        assertNull(page.nextCursor());
        assertEquals(3, page.items().size());
        assertEquals("anonymous", page.items().get(0).actorKind());
        assertNull(page.items().get(0).actorEmail());
        assertEquals("invalid_credentials", page.items().get(0).reason());
        assertTrue(page.items().get(0).detail().isEmpty());
        assertEquals("ok", page.items().get(1).outcome());
        assertEquals(4, page.items().get(1).detail().size());
        assertEquals(2L, page.items().get(1).detail().get("afterRevision"));
        assertNull(page.items().get(2).reason());
        assertTrue(page.items().get(2).detail().isEmpty());
    }

    @Test
    void signsCursorAndBindsItToAdminFilterAndLimit() {
        when(repository.page(any(), any(), any(), any(), any(), any(), any(), anyInt()))
                .thenReturn(List.of(row(3, "admin", "member.block", "succeeded", "abuse", "{}"),
                        row(2, "admin", "member.block", "succeeded", "abuse", "{}")));
        var service = service();
        var page = service.list("admin-1", "member.block", null, null, "abuse", null, 1);
        assertNotNull(page.nextCursor());
        assertEquals(1, page.items().size());
        assertEquals(3, page.items().get(0).id());

        var cursor = page.nextCursor();
        assertEquals(ErrorCode.INVALID_CURSOR, assertThrows(CustomException.class,
                () -> service.list("admin-2", "member.block", null, null, "abuse", cursor, 1))
                .getErrorCode());
        assertEquals(ErrorCode.INVALID_CURSOR, assertThrows(CustomException.class,
                () -> service.list("admin-1", "member.unblock", null, null, "abuse", cursor, 1))
                .getErrorCode());
        assertEquals(ErrorCode.INVALID_CURSOR, assertThrows(CustomException.class,
                () -> service.list("admin-1", "member.block", null, null, "abuse", cursor, 2))
                .getErrorCode());
        int signatureAt = cursor.indexOf('.') + 1;
        String corrupted = cursor.substring(0, signatureAt)
                + (cursor.charAt(signatureAt) == 'A' ? 'B' : 'A')
                + cursor.substring(signatureAt + 1);
        assertEquals(ErrorCode.INVALID_CURSOR, assertThrows(CustomException.class,
                () -> service.list("admin-1", "member.block", null, null, "abuse", corrupted, 1))
                .getErrorCode());

        service.list("admin-1", "member.block", null, null, "abuse", cursor, null);
        verify(repository).page(eq("member.block"), isNull(), isNull(), eq("%abuse%"),
                eq(NOW), eq(NOW.minusSeconds(1)), eq(3L), eq(2));
    }

    @Test
    void normalizesEscapedSearchAndRejectsInvalidInput() {
        when(repository.page(any(), any(), any(), any(), any(), any(), any(), anyInt()))
                .thenReturn(List.of());
        var service = service();
        var empty = service.list("admin-1", " ", null, null, "  A%!_  ", null, null);
        assertTrue(empty.items().isEmpty());
        assertNull(empty.nextCursor());
        verify(repository).page(isNull(), isNull(), isNull(), eq("%a!%!!!_%"),
                eq(NOW), isNull(), isNull(), eq(51));
        assertEquals(ErrorCode.INVALID_REQUEST, assertThrows(CustomException.class,
                () -> service.list("admin-1", null, null, null, "bad\nquery", null, null))
                .getErrorCode());
        assertEquals(ErrorCode.INVALID_REQUEST, assertThrows(CustomException.class,
                () -> service.list("admin-1", null, null, null, null, null, 101))
                .getErrorCode());
    }

    @Test
    void storageFailureIsNotRepresentedAsAnEmptyPage() {
        when(repository.page(any(), any(), any(), any(), any(), any(), any(), anyInt()))
                .thenThrow(new org.springframework.dao.DataAccessResourceFailureException("offline"));
        var failure = assertThrows(CustomException.class,
                () -> service().list("admin-1", null, null, null, null, null, null));
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, failure.getErrorCode());
    }

    private AdminAuditQueryService service() {
        return new AdminAuditQueryService(repository, JsonMapper.builder().build(),
                new CsrfKeyRing("test", "test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"),
                Clock.fixed(NOW, ZoneOffset.UTC));
    }

    private static AuditRecord row(long id, String kind, String action, String outcome,
            String reason, String detail) {
        return new AuditRecord(id, NOW.minusSeconds(1), kind, "admin-1", "admin@example.com",
                action, "member", "member-1", reason, outcome, detail);
    }
}
