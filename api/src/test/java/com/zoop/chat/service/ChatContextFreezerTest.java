package com.zoop.chat.service;

import java.io.IOException;
import java.io.InputStream;
import java.io.UncheckedIOException;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

import com.zoop.chat.dto.ChatContextItem;
import com.zoop.chat.dto.ChatContextRequest;
import com.zoop.chat.dto.ChatPeriod;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.graph.read.DisclosureExclusions;
import com.zoop.graph.read.PublicGraphReader;
import com.zoop.graph.snapshot.FixtureGraphSnapshotStore;
import com.zoop.graph.version.GraphVersionRecord;
import com.zoop.graph.version.GraphVersionRepository;
import com.zoop.graph.version.GraphVersionSelector;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.function.Executable;

import static org.junit.jupiter.api.Assertions.*;

/** D-AI-01: the selection is frozen through the public graph read path of the synthetic fixtures. */
class ChatContextFreezerTest {
    private static final Instant NOW = Instant.parse("2026-10-21T03:00:00Z");
    private static final String OLD = "fixture-2026-10-01";
    private static final String ACTIVE = "fixture-2026-10-08";
    private static final String HYNIX = "KRX:000660";
    private static final String HBM_SUPPLY = "iss-fixture-hbm-supply";
    private static final String SUPPLY_NVDA = "ev-912843a071ee90c12ee7e909c65f06ce748d2a35c7c29c6c871faac130e4f395";

    private final Set<String> unreadable = new HashSet<>();
    private final List<String> accessChecks = new ArrayList<>();

    @Test
    void aQuestionWithoutSelectionPinsTheActiveVersionOrNothing() {
        var frozen = freezer(true).freeze(null, "req-test");
        assertEquals(ACTIVE, frozen.graphVersionId());
        assertEquals(ACTIVE, frozen.context().graphVersion());
        assertEquals(List.of(), frozen.context().items());
        assertNull(frozen.context().asOf());

        var none = freezer(false).freeze(new ChatContextRequest(List.of(), List.of(),
                new ChatPeriod("2026-10-01", "2026-10-20"), null, null), "req-test");
        assertNull(none.graphVersionId());
        assertEquals(new ChatPeriod("2026-10-01", "2026-10-20"), none.context().period());
    }

    @Test
    void selectedTargetsAreFrozenWithLabelsCompaniesAndEvidenceCount() {
        var frozen = freezer(true).freeze(new ChatContextRequest(List.of(HYNIX, HBM_SUPPLY), List.of(), null, null, null), "req-test");
        assertEquals(List.of(new ChatContextItem(HYNIX, "company", "SK하이닉스"),
                new ChatContextItem(HBM_SUPPLY, "issue", "[합성] 차세대 GPU용 HBM 공급 계약")), frozen.context().items());
        assertEquals(List.of(HYNIX, "NASDAQ:NVDA"), frozen.companyIds());
        assertEquals(3, frozen.context().evidenceCount());
        assertEquals(ACTIVE, frozen.graphVersionId());
    }

    @Test
    void explicitEvidenceNarrowsTheSelectionAndIsShownAsSelected() {
        var narrowed = freezer(true).freeze(new ChatContextRequest(List.of(HBM_SUPPLY), List.of(SUPPLY_NVDA), null, null,
                null), "req-test");
        assertEquals(1, narrowed.context().evidenceCount());
        assertEquals(List.of(HBM_SUPPLY, SUPPLY_NVDA),
                narrowed.context().items().stream().map(ChatContextItem::id).toList());

        var only = freezer(true).freeze(new ChatContextRequest(List.of(), List.of(SUPPLY_NVDA), null, null, null), "req-test");
        assertEquals(1, only.context().evidenceCount());
        assertEquals("evidence", only.context().items().getFirst().kind());
    }

    @Test
    void theSameTargetsNarrowedToDifferentEvidenceKeepDifferentSelections() {
        String supplyHynix = "ev-bb3008cb36e9b51c0d2fd77af059259332b1887cc04862e185a496c3dcc9e421";
        var first = freezer(true).freeze(new ChatContextRequest(List.of(SUPPLY_NVDA, supplyHynix), List.of(SUPPLY_NVDA),
                null, null, null), "req-test");
        var second = freezer(true).freeze(new ChatContextRequest(List.of(SUPPLY_NVDA, supplyHynix), List.of(supplyHynix),
                null, null, null), "req-test");
        // The public context cannot tell them apart; the stored selection can.
        assertEquals(first.context(), second.context());
        assertEquals(new FrozenSelection(List.of(SUPPLY_NVDA, supplyHynix), List.of(SUPPLY_NVDA), List.of(SUPPLY_NVDA)),
                first.selection());
        assertEquals(List.of(supplyHynix), second.selection().evidencePool());
        assertEquals(FrozenSelection.NONE, freezer(true).freeze(null, "req-test").selection());
    }

    @Test
    void anEvidenceSelectionMustPassThePublicEvidenceReadAtThePinnedVersion() {
        var company = freezer(true).freeze(new ChatContextRequest(List.of(HYNIX), List.of(), null, null, null), "req-test");
        assertEquals(2, company.context().evidenceCount());
        assertTrue(accessChecks.isEmpty(), "a company, issue or edge needs no evidence read");

        freezer(true).freeze(new ChatContextRequest(List.of(), List.of(SUPPLY_NVDA), null, null, null), "req-test");
        assertEquals(List.of(SUPPLY_NVDA + "@" + ACTIVE + "@null"), accessChecks);

        unreadable.add(SUPPLY_NVDA);
        assertError(ErrorCode.INVALID_REQUEST, () -> freezer(true).freeze(
                new ChatContextRequest(List.of(), List.of(SUPPLY_NVDA), null, null, null), "req-test"));
        assertError(ErrorCode.INVALID_REQUEST, () -> freezer(true).freeze(
                new ChatContextRequest(List.of(SUPPLY_NVDA), List.of(), null, null, null), "req-test"));
    }

    @Test
    void aSpanNoVisibleIssueOrRelationCitesIsAcceptedOnlyWhenThePublicReadProvesIt() {
        // With its issue excluded, the span stays listed in the snapshot but nothing visible cites it, like a span only a
        // structural basis cites: the public evidence read (receipt membership) decides, not the lookup.
        var excluded = new DisclosureExclusions(1, Set.of(HBM_SUPPLY), Set.of(), Set.of());
        var proven = freezer(true, excluded).freeze(
                new ChatContextRequest(List.of(), List.of(SUPPLY_NVDA), null, null, null), "req-test");
        assertEquals("evidence", proven.context().items().getFirst().kind());
        assertEquals(List.of(SUPPLY_NVDA), proven.selection().evidencePool());

        unreadable.add(SUPPLY_NVDA);
        assertError(ErrorCode.INVALID_REQUEST, () -> freezer(true, excluded).freeze(
                new ChatContextRequest(List.of(), List.of(SUPPLY_NVDA), null, null, null), "req-test"));
    }

    @Test
    void asOfPinsTheVersionActiveThenAndIsKept() {
        Instant asOf = Instant.parse("2026-10-05T00:00:00Z");
        var frozen = freezer(true).freeze(new ChatContextRequest(List.of(HYNIX), List.of(), null, asOf, null), "req-test");
        assertEquals(OLD, frozen.graphVersionId());
        assertEquals(asOf, frozen.context().asOf());

        var versionOnly = freezer(true).freeze(new ChatContextRequest(List.of(), List.of(), null, null, OLD), "req-test");
        assertEquals(OLD, versionOnly.graphVersionId());
        assertNull(versionOnly.context().asOf());
    }

    @Test
    void unknownSelectionOrVersionIsRefusedAndNeverReplaced() {
        assertError(ErrorCode.INVALID_REQUEST, () -> freezer(true).freeze(
                new ChatContextRequest(List.of("KRX:999999"), List.of(), null, null, null), "req-test"));
        assertError(ErrorCode.INVALID_REQUEST, () -> freezer(true).freeze(
                new ChatContextRequest(List.of(), List.of(HYNIX), null, null, null), "req-test"));
        assertError(ErrorCode.VERSION_UNAVAILABLE, () -> freezer(true).freeze(
                new ChatContextRequest(List.of(), List.of(), null, null, "fixture-missing"), "req-test"));
        assertError(ErrorCode.VERSION_UNAVAILABLE, () -> freezer(false).freeze(
                new ChatContextRequest(List.of(HYNIX), List.of(), null, null, null), "req-test"));
    }

    private ChatContextFreezer freezer(boolean versions) {
        return freezer(versions, DisclosureExclusions.NONE);
    }

    /** The public evidence read is stubbed: every id is readable except those in {@link #unreadable}; checks are recorded. */
    private ChatContextFreezer freezer(boolean versions, DisclosureExclusions exclusions) {
        var selector = new GraphVersionSelector(repository(versions), Clock.fixed(NOW, ZoneOffset.UTC));
        var reader = new PublicGraphReader(selector,
                new FixtureGraphSnapshotStore(ChatContextFreezerTest.class.getClassLoader()), pinned -> exclusions);
        return new ChatContextFreezer(reader, selector, (id, version, asOf, requestId) -> {
            accessChecks.add(id + "@" + version + "@" + asOf);
            return !unreadable.contains(id);
        });
    }

    /** Both fixtures, activated at 2026-10-01 and 2026-10-08; without versions nothing was ever published. */
    private static GraphVersionRepository repository(boolean versions) {
        Map<String, GraphVersionRecord> known = versions ? Map.of(OLD, record(OLD, false), ACTIVE, record(ACTIVE, true))
                : Map.of();
        return new GraphVersionRepository() {
            public Optional<GraphVersionRecord> find(String id) { return Optional.ofNullable(known.get(id)); }
            public Optional<GraphVersionRecord> active() { return Optional.ofNullable(known.get(ACTIVE)); }
            public Optional<String> activeVersionIdAt(Instant asOf) {
                if (known.isEmpty() || asOf.isBefore(Instant.parse("2026-10-01T00:00:00Z"))) return Optional.empty();
                return Optional.of(asOf.isBefore(Instant.parse("2026-10-08T00:00:00Z")) ? OLD : ACTIVE);
            }
            public boolean everActivated(String id) { return known.containsKey(id); }
        };
    }

    private static GraphVersionRecord record(String id, boolean active) {
        return new GraphVersionRecord(id, 1, "fixture", "artifact-" + id, FixtureGraphSnapshotStore.URI_PREFIX + id + ".json",
                FixtureGraphSnapshotStore.sha256(bytes(id)), active);
    }

    private static byte[] bytes(String id) {
        try (InputStream in = ChatContextFreezerTest.class.getClassLoader()
                .getResourceAsStream("graph-fixtures/" + id + ".json")) {
            return in.readAllBytes();
        } catch (IOException exception) {
            throw new UncheckedIOException(exception);
        }
    }

    private static void assertError(ErrorCode expected, Executable call) {
        assertEquals(expected, assertThrows(CustomException.class, call).getErrorCode());
    }
}
