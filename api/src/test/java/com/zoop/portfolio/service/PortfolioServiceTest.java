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
    private TestQuoteProvider quotes;
    private PortfolioService service;

    @BeforeEach
    void setUp() {
        catalog = new MockPortfolioCatalog(new ObjectMapper());
        repository = new MemoryRepository();
        quotes = new TestQuoteProvider();
        service = new PortfolioService(catalog, repository, quotes, Clock.fixed(NOW, ZoneOffset.UTC));
    }

    @Test
    void catalogHasTwoFixedSyntheticProfilesAndSupportsZeroCash() {
        assertEquals(2, catalog.all().size());
        assertEquals(0, catalog.find("demo-balanced").orElseThrow().cash().amount().signum());
        assertEquals(2, catalog.page(null, 2).items().size());
        assertNull(catalog.page(null, 2).nextCursor());
    }

    @Test
    void profilePreviewValuesHoldingsWithoutCreatingMemberConnection() {
        quotes.result = holding -> PortfolioQuoteProvider.QuoteResult.available(
                new java.math.BigDecimal("100"), "USD", NOW, "Synthetic quotes");

        var preview = service.getProfile("demo-growth", "preview-1");

        assertEquals(3, preview.holdings().size());
        assertEquals("available", preview.valuation().weightStatus());
        assertTrue(repository.connections.isEmpty());
    }

    @Test
    void connectionIsIdempotentAndKeyReuseForDifferentProfileConflicts() {
        var first = service.connect(MEMBER, "demo-growth", "connect-1", "req-1");
        var retry = service.connect(MEMBER, "demo-growth", "connect-1", "req-2");
        assertEquals(first.id(), retry.id());
        assertEquals(first.connectedAt(), retry.connectedAt());
        assertEquals("MOCK-KR-1001", first.accountId());
        assertEquals(3, first.holdingsCount());
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
    void portfolioCalculatesMarketValuesAndWeightsFromOneCurrencyQuoteSet() {
        quotes.result = holding -> PortfolioQuoteProvider.QuoteResult.available(
                holding.ticker().equals("NVDA") ? new java.math.BigDecimal("100") : new java.math.BigDecimal("200"),
                "USD", NOW.minusSeconds(30), "Synthetic quotes");
        service.connect(MEMBER, "demo-growth", "growth", "connect");

        var portfolio = service.getMyPortfolio(MEMBER, "portfolio");

        assertEquals("available", portfolio.valuation().weightStatus());
        assertEquals("USD", portfolio.valuation().currency());
        assertEquals(0, new java.math.BigDecimal("2000").compareTo(portfolio.valuation().totalMarketValue()));
        assertEquals(0, new java.math.BigDecimal("1200").compareTo(portfolio.holdings().get(0).marketValue()));
        assertEquals(0, new java.math.BigDecimal("0.6").compareTo(portfolio.holdings().get(0).weight()));
        assertInstanceOf(com.zoop.portfolio.dto.HoldingOut.Available.class,
                portfolio.holdings().get(0).quote());
    }

    @Test
    void portfolioDoesNotSumMixedCurrenciesOrInventMissingPrices() {
        quotes.result = holding -> holding.ticker().equals("NVDA")
                ? PortfolioQuoteProvider.QuoteResult.available(new java.math.BigDecimal("100"), "USD", NOW, "Quotes")
                : PortfolioQuoteProvider.QuoteResult.available(new java.math.BigDecimal("200"), "KRW", NOW, "Quotes");
        service.connect(MEMBER, "demo-growth", "growth", "connect");
        var mixed = service.getMyPortfolio(MEMBER, "mixed");
        assertEquals("mixed_currency", mixed.valuation().weightUnavailableCode());
        assertNull(mixed.valuation().totalMarketValue());
        assertNull(mixed.holdings().get(0).weight());

        quotes.result = holding -> PortfolioQuoteProvider.QuoteResult.unavailable("not_connected");
        var missing = service.getMyPortfolio(MEMBER, "missing");
        assertEquals("missing_price", missing.valuation().weightUnavailableCode());
        assertNull(missing.holdings().get(0).marketValue());
        assertInstanceOf(com.zoop.portfolio.dto.HoldingOut.Unavailable.class,
                missing.holdings().get(0).quote());
    }

    @Test
    void zeroTotalIsAValueButHasNoWeights() {
        quotes.result = holding -> PortfolioQuoteProvider.QuoteResult.available(
                java.math.BigDecimal.ZERO, "USD", NOW, "Quotes");
        service.connect(MEMBER, "demo-growth", "growth", "connect");
        var portfolio = service.getMyPortfolio(MEMBER, "zero");
        assertEquals(0, java.math.BigDecimal.ZERO.compareTo(portfolio.valuation().totalMarketValue()));
        assertEquals("zero_total", portfolio.valuation().weightUnavailableCode());
        assertNull(portfolio.holdings().get(0).weight());
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

    private static final class TestQuoteProvider implements PortfolioQuoteProvider {
        java.util.function.Function<com.zoop.portfolio.model.MockHolding, QuoteResult> result =
                holding -> QuoteResult.unavailable("not_connected");
        @Override public QuoteResult quote(com.zoop.portfolio.model.MockHolding holding) {
            return result.apply(holding);
        }
    }
}
