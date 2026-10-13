package com.zoop.auth.service;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;

import com.zoop.auth.repository.TermRepository;
import com.zoop.auth.repository.TermRow;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DataRetrievalFailureException;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class TermServiceTest {
    private static final Instant NOW = Instant.parse("2026-10-13T08:00:00Z");

    @Test
    void noLimitReturnsFullListAndDistinguishesUnavailableBody() {
        TermRepository repository = (at, after, count) -> List.of(
                new TermRow("privacy", "개인정보 처리방침", true, null, null),
                new TermRow("service", "서비스 이용약관", true, "2026-10-13.1", "승인 본문"));
        var response = service(repository).list(null, null);

        assertEquals(2, response.items().size());
        assertNull(response.nextCursor());
        assertFalse(response.items().get(0).bodyAvailable());
        assertNull(response.items().get(0).version());
        assertTrue(response.items().get(1).bodyAvailable());
        assertEquals("승인 본문", response.items().get(1).body());
    }

    @Test
    void cursorContinuesAtSameSnapshotAndRejectsChangedLimit() {
        var requests = new ArrayList<String>();
        TermRepository repository = (at, after, count) -> {
            requests.add(at + ":" + after + ":" + count);
            if (after.isEmpty()) {
                return List.of(
                        new TermRow("privacy", "개인정보 처리방침", true, "v1", "본문1"),
                        new TermRow("service", "서비스 이용약관", true, "v1", "본문2"));
            }
            return List.of(new TermRow("service", "서비스 이용약관", true, "v1", "본문2"));
        };
        var service = service(repository);

        var first = service.list(null, 1);
        assertEquals("privacy", first.items().getFirst().id());
        assertNotNull(first.nextCursor());
        var second = service.list(first.nextCursor(), null);
        assertEquals("service", second.items().getFirst().id());
        assertNull(second.nextCursor());
        assertEquals(List.of(NOW + "::2", NOW + ":privacy:2"), requests);

        var invalid = assertThrows(CustomException.class,
                () -> service.list(first.nextCursor(), 2));
        assertEquals(ErrorCode.INVALID_CURSOR, invalid.getErrorCode());
    }

    @Test
    void invalidParametersAndUnavailableRepositoryUseContractErrors() {
        var service = service((at, after, count) -> {
            throw new DataRetrievalFailureException("database detail");
        });
        assertEquals(ErrorCode.INVALID_REQUEST,
                assertThrows(CustomException.class, () -> service.list(null, 0)).getErrorCode());
        assertEquals(ErrorCode.INVALID_CURSOR,
                assertThrows(CustomException.class, () -> service.list("not-base64!", null)).getErrorCode());
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE,
                assertThrows(CustomException.class, () -> service.list(null, null)).getErrorCode());
    }

    private static TermService service(TermRepository repository) {
        return new TermService(repository, Clock.fixed(NOW, ZoneOffset.UTC));
    }
}
