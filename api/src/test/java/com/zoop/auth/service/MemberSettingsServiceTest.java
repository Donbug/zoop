package com.zoop.auth.service;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

import com.zoop.auth.repository.MemberSettingsRepository;
import com.zoop.auth.repository.MemberSettingsRow;
import com.zoop.auth.service.MemberSessionService.MemberPrincipal;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.json.StrictJson;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

class MemberSettingsServiceTest {
    private static final Instant NOW = Instant.parse("2026-10-16T00:00:00Z");
    private static final MemberPrincipal MEMBER = new MemberPrincipal("member-1", "session-1");
    private final MemoryRepository repository = new MemoryRepository();
    private final MemberSettingsService service = new MemberSettingsService(repository,
            Clock.fixed(NOW, ZoneOffset.UTC));

    @Test
    void getReturnsInitialUnansweredSettingsAndRequestMetadata() {
        var response = service.get(MEMBER, "req-1");
        assertNull(response.mode());
        assertNull(response.investor());
        assertEquals(List.of(), response.watchlistIds());
        assertFalse(response.completed());
        assertFalse(response.tutorialCompleted());
        assertEquals(1, response.version());
        assertEquals("req-1", response.metadata().requestId());
        assertEquals(NOW, response.metadata().asOf());
    }

    @Test
    void rejectsCompletingSettingsUntilInvestorAndModeAreSelected() {
        var error = assertThrows(CustomException.class,
                () -> service.update(MEMBER, json("""
                        {"version":1,"completed":true}
                        """), "incomplete"));

        assertEquals(ErrorCode.INVALID_REQUEST, error.getErrorCode());
        assertFalse(repository.row.completed());
        assertEquals(0, repository.writeCount);
    }

    @Test
    void updatePersistsInvestorModeWatchlistAndIndependentTutorialState() {
        repository.existingCompanies = List.of("NASDAQ:NVDA", "KRX:005930");
        var response = service.update(MEMBER, json("""
                {"version":1,"investor":true,"mode":"assets","watchlistIds":["NASDAQ:NVDA","KRX:005930"],"completed":true}
                """), "req-2");
        assertEquals("assets", response.mode());
        assertEquals(true, response.investor());
        assertEquals(List.of("NASDAQ:NVDA", "KRX:005930"), response.watchlistIds());
        assertTrue(response.completed());
        assertFalse(response.tutorialCompleted());
        assertEquals(2, response.version());
        assertEquals(1, repository.writeCount);
    }

    @Test
    void explicitNullModeAndOmittedFieldsKeepStoredValues() {
        repository.row = new MemberSettingsRow("watchlist", false, false, true, 4, List.of("NASDAQ:NVDA"));
        var response = service.update(MEMBER, json("""
                {"version":4,"mode":null,"investor":null}
                """), "req-3");
        assertEquals("watchlist", response.mode());
        assertNull(response.investor());
        assertFalse(response.completed());
        assertTrue(response.tutorialCompleted());
        assertEquals(List.of("NASDAQ:NVDA"), response.watchlistIds());
        assertEquals(5, response.version());
    }

    @Test
    void staleIdenticalRetryIsIdempotentButChangedStaleRequestConflicts() {
        repository.row = new MemberSettingsRow("assets", true, true, false, 8, List.of());
        var retry = service.update(MEMBER, json("""
                {"version":7,"mode":"assets","investor":true,"completed":true}
                """), "retry");
        assertEquals(8, retry.version());
        assertEquals(0, repository.writeCount);
        var error = assertThrows(CustomException.class,
                () -> service.update(MEMBER, json("""
                        {"version":7,"investor":false}
                        """), "stale"));
        assertEquals(ErrorCode.REVISION_CONFLICT, error.getErrorCode());
    }

    @Test
    void rejectsDuplicateAndUnknownWatchlistIdsWithoutSaving() {
        repository.existingCompanies = List.of("NASDAQ:NVDA");
        var duplicate = assertThrows(CustomException.class,
                () -> service.update(MEMBER, json("""
                        {"version":1,"watchlistIds":["NASDAQ:NVDA","NASDAQ:NVDA"]}
                        """), "duplicate"));
        assertEquals(ErrorCode.INVALID_REQUEST, duplicate.getErrorCode());
        var unknown = assertThrows(CustomException.class,
                () -> service.update(MEMBER, json("""
                        {"version":1,"watchlistIds":["NOPE"]}
                        """), "unknown"));
        assertEquals(ErrorCode.RESOURCE_NOT_FOUND, unknown.getErrorCode());
        assertEquals(0, repository.writeCount);
    }

    @Test
    void rejectsMalformedOrUnknownFields() {
        assertEquals(ErrorCode.INVALID_REQUEST, assertThrows(CustomException.class,
                () -> service.update(MEMBER, json("""
                        {"version":0}
                        """), "invalid")).getErrorCode());
        assertEquals(ErrorCode.INVALID_REQUEST, assertThrows(CustomException.class,
                () -> service.update(MEMBER, json("""
                        {"version":1,"unexpected":true}
                        """), "invalid")).getErrorCode());
    }

    private static tools.jackson.databind.JsonNode json(String source) {
        return StrictJson.parseObject(source).node();
    }

    private static final class MemoryRepository implements MemberSettingsRepository {
        MemberSettingsRow row = new MemberSettingsRow(null, null, false, false, 1, List.of());
        List<String> existingCompanies = List.of();
        int writeCount;

        @Override public Optional<MemberSettingsRow> find(String memberId) { return Optional.of(row); }
        @Override public Optional<MemberSettingsRow> findForUpdate(String memberId) { return Optional.of(row); }
        @Override public void update(String memberId, String mode, Boolean investor, boolean completed,
                boolean tutorialCompleted, long expectedVersion, long nextVersion) {
            writeCount++;
            row = new MemberSettingsRow(mode, investor, completed, tutorialCompleted, nextVersion, row.watchlistIds());
        }
        @Override public boolean companiesExist(Iterable<String> companyIds) {
            var ids = new ArrayList<String>();
            companyIds.forEach(ids::add);
            return existingCompanies.containsAll(ids);
        }
        @Override public void replaceWatchlist(String memberId, Iterable<String> companyIds) {
            var ids = new ArrayList<String>();
            companyIds.forEach(ids::add);
            row = new MemberSettingsRow(row.mode(), row.investor(), row.completed(), row.tutorialCompleted(), row.version(), ids);
        }
    }
}
