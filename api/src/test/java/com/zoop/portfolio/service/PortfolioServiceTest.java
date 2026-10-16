package com.zoop.portfolio.service;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.HashMap;
import java.util.Map;
import java.util.Optional;

import tools.jackson.databind.ObjectMapper;
import com.zoop.auth.service.MemberSessionService.MemberPrincipal;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.portfolio.repository.PortfolioConnectionRepository;
import com.zoop.portfolio.repository.PortfolioConnectionRow;
import com.zoop.portfolio.repository.PortfolioIdempotencyRow;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

class PortfolioServiceTest {
    private static final Instant NOW = Instant.parse("2026-10-16T12:00:00Z");
    private static final MemberPrincipal MEMBER = new MemberPrincipal("member-a", "session-a");

    private MockPortfolioCatalog catalog;
    private MemoryRepository repository;
    private PortfolioService service;

    @BeforeEach
    void setUp() {
        catalog = new MockPortfolioCatalog(new ObjectMapper());
        repository = new MemoryRepository();
        service = new PortfolioService(catalog, repository, Clock.fixed(NOW, ZoneOffset.UTC));
    }

    @Test
    void catalogHasTwoFixedSyntheticProfilesAndSupportsZeroCash() {
        assertEquals(2, catalog.all().size());
        assertEquals(0, catalog.find("demo-balanced").orElseThrow().cash().amount().signum());
        assertEquals(2, catalog.page(null, 2).items().size());
        assertNull(catalog.page(null, 2).nextCursor());
    }

    @Test
    void connectionIsIdempotentAndKeyReuseForDifferentProfileConflicts() {
        var first = service.connect(MEMBER, "demo-growth", "connect-1", "req-1");
        var retry = service.connect(MEMBER, "demo-growth", "connect-1", "req-2");
        assertEquals(first.id(), retry.id());
        assertEquals(first.connectedAt(), retry.connectedAt());
        assertEquals("MOCK-KR-1001", first.accountId());
        assertEquals(2, first.holdingsCount());
        assertEquals(1, repository.connections.size());

        var sameProfileNewKey = service.connect(MEMBER, "demo-growth", "connect-2", "req-3");
        assertEquals(first.id(), sameProfileNewKey.id());

        var error = assertThrows(CustomException.class,
                () -> service.connect(MEMBER, "demo-balanced", "connect-1", "req-4"));
        assertEquals(ErrorCode.IDEMPOTENCY_CONFLICT, error.getErrorCode());
    }

    @Test
    void changingProfileReplacesConnectionAndDisconnectOnlyRemovesCurrentOwnerConnection() {
        var first = service.connect(MEMBER, "demo-growth", "connect-growth", "req-1");
        var replacement = service.connect(MEMBER, "demo-balanced", "connect-balanced", "req-2");
        assertNotEquals(first.id(), replacement.id());
        assertEquals("demo-balanced", repository.connections.get(MEMBER.memberId()).mockPortfolioId());

        assertThrows(CustomException.class, () -> service.disconnect(MEMBER, first.id()));
        service.disconnect(MEMBER, replacement.id());
        assertTrue(repository.connections.isEmpty());
    }

    @Test
    void portfolioDistinguishesUnconnectedAndLeavesPricesUnavailable() {
        var initial = service.getMyPortfolio(MEMBER, "portfolio-1");
        assertFalse(initial.connected());
        assertNull(initial.connection());
        assertTrue(initial.holdings().isEmpty());
        assertNull(initial.valuation());

        assertEquals(ErrorCode.RESOURCE_NOT_FOUND, assertThrows(CustomException.class,
                () -> service.connect(MEMBER, "demo-empty", "connect-empty", "connect-req")).getErrorCode());
    }

    @Test
    void rejectsUnknownProfilesAndMalformedCursor() {
        assertEquals(ErrorCode.RESOURCE_NOT_FOUND, assertThrows(CustomException.class,
                () -> service.getProfile("not-real", "req")).getErrorCode());
        assertEquals(ErrorCode.RESOURCE_NOT_FOUND, assertThrows(CustomException.class,
                () -> service.connect(MEMBER, "not-real", "key", "req")).getErrorCode());
        assertEquals(ErrorCode.INVALID_CURSOR, assertThrows(CustomException.class,
                () -> service.listProfiles("bad", 1, "req")).getErrorCode());
        String cursor = service.listProfiles(null, 1, "req").nextCursor();
        assertEquals(ErrorCode.INVALID_CURSOR, assertThrows(CustomException.class,
                () -> service.listProfiles(cursor, 2, "req")).getErrorCode());
    }

    private static final class MemoryRepository implements PortfolioConnectionRepository {
        private final Map<String, PortfolioConnectionRow> connections = new HashMap<>();
        private final Map<String, PortfolioIdempotencyRow> idempotency = new HashMap<>();

        @Override public boolean lockMember(String memberId) { return true; }
        @Override public Optional<PortfolioConnectionRow> findConnection(String memberId) {
            return Optional.ofNullable(connections.get(memberId));
        }
        @Override public Optional<PortfolioConnectionRow> findConnection(String memberId, String connectionId) {
            return findConnection(memberId).filter(row -> row.connectionId().equals(connectionId));
        }
        @Override public Optional<PortfolioIdempotencyRow> findIdempotency(String memberId, String key) {
            return Optional.ofNullable(idempotency.get(memberId + ":" + key));
        }
        @Override public void saveConnection(String memberId, PortfolioConnectionRow row) {
            connections.put(memberId, row);
        }
        @Override public void saveIdempotency(String memberId, String key, PortfolioIdempotencyRow row) {
            idempotency.put(memberId + ":" + key, row);
        }
        @Override public boolean deleteConnection(String memberId, String connectionId) {
            PortfolioConnectionRow current = connections.get(memberId);
            return current != null && current.connectionId().equals(connectionId)
                    && connections.remove(memberId, current);
        }
    }
}
