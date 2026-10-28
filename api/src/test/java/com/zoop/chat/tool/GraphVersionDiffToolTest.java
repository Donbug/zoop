package com.zoop.chat.tool;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.IOException;
import java.io.InputStream;
import java.io.UncheckedIOException;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

import com.zoop.chat.service.ChatEvidenceAccess;
import com.zoop.document.evidence.service.EvidenceService.Readability;
import com.zoop.graph.read.DisclosureExclusions;
import com.zoop.graph.read.PublicGraphReader;
import com.zoop.graph.snapshot.FixtureGraphSnapshotStore;
import com.zoop.graph.version.GraphVersionRecord;
import com.zoop.graph.version.GraphVersionRepository;
import com.zoop.graph.version.GraphVersionSelector;
import org.junit.jupiter.api.Test;

/**
 * D-AI-02 Q05 reads: graph.version.diff over the two synthetic public graph fixtures. 2026-10-08 added the AI accelerator
 * issue, AMD, and the issue's relations to AMD and TSMC; nothing was removed.
 */
class GraphVersionDiffToolTest {
    private static final Instant NOW = Instant.parse("2026-10-21T03:00:00Z");
    private static final String OLD = "fixture-2026-10-01";
    private static final String ACTIVE = "fixture-2026-10-08";
    private static final String AI_ACCEL = "iss-fixture-ai-accel";
    private static final String AMD = "NASDAQ:AMD";
    private static final String TSMC = "NYSE:TSM";
    private static final ChatToolScope SCOPE = new ChatToolScope("job-1", ACTIVE, null);

    private final Set<String> denied = new HashSet<>();
    private DisclosureExclusions exclusions = DisclosureExclusions.NONE;

    @Test
    void withoutAPeriodTheMapIsComparedWithThePreviousPublicVersion() {
        var out = tool().read(SCOPE, whole(null));
        assertEquals(OLD + ".." + ACTIVE, out.dataVersion());
        assertEquals(List.of(AMD, AI_ACCEL), out.items().stream().filter(i -> !"edge".equals(i.kind()))
                .map(ChatToolItem::id).toList(), "additions: companies, then issues, then edges");
        assertEquals(2, out.items().stream().filter(i -> "edge".equals(i.kind())).count());
        assertTrue(out.items().stream().allMatch(i -> i.label().startsWith("[새로 생김] ")));
        var amdEdge = out.items().stream().filter(i -> "edge".equals(i.kind()) && i.companyIds().equals(List.of(AMD)))
                .findFirst().orElseThrow();
        assertTrue(amdEdge.label().contains("AI 가속기") && amdEdge.label().contains("AMD"), amdEdge.label());
        assertFalse(amdEdge.evidenceIds().isEmpty(), "an added relation carries the evidence the map shows for it");
        assertFalse(out.truncated());
    }

    @Test
    void aWrittenPeriodComparesWithTheMapPublicThen() {
        assertEquals(OLD + ".." + ACTIVE, tool().read(SCOPE, whole(Instant.parse("2026-10-05T00:00:00Z"))).dataVersion());

        var same = tool().read(SCOPE, whole(Instant.parse("2026-10-09T00:00:00Z")));
        assertEquals(ACTIVE + ".." + ACTIVE, same.dataVersion());
        assertTrue(same.items().isEmpty() && !same.truncated(), "the same map then and now: nothing changed");

        var before = tool().read(SCOPE, whole(Instant.parse("2026-09-01T00:00:00Z")));
        assertTrue(before.items().isEmpty());
        assertTrue(before.truncated(), "no map was public then: the comparison is cut, never \"nothing changed\"");
        var first = tool().read(new ChatToolScope("job-1", OLD, null), whole(null));
        assertTrue(first.items().isEmpty() && first.truncated(), "the first public map has nothing before it");
    }

    @Test
    void aPeriodAfterThePinnedMomentIsNeverComparedTheWrongWayRound() {
        // The run reads the map as of 2026-10-05 (10-01); "since 10-09" would make 10-08 the "earlier" map.
        var pinnedPast = new ChatToolScope("job-1", OLD, Instant.parse("2026-10-05T00:00:00Z"));
        var out = tool().read(pinnedPast, whole(Instant.parse("2026-10-09T00:00:00Z")));
        assertTrue(out.items().isEmpty(), "no additions shown as removals");
        assertTrue(out.truncated(), "it cannot be compared, which is not \"nothing changed\"");
        assertEquals(OLD, out.dataVersion());
    }

    @Test
    void selectedEvidenceAloneComparesTheWholeMap() {
        var evidence = "ev-" + "a".repeat(64);
        var out = tool().read(SCOPE, new ChatToolRequest("graph.version.diff", List.of(evidence), 20));
        assertEquals(tool().read(SCOPE, whole(null)).items(), out.items(),
                "evidence names no company or issue, so nothing is narrowed away");
    }

    @Test
    void targetsNarrowTheChangesToThoseCompaniesAndIssues() {
        var tsmc = tool().read(SCOPE, new ChatToolRequest("graph.version.diff", List.of(TSMC), 20));
        assertEquals(List.of("issue", "edge"), tsmc.items().stream().map(ChatToolItem::kind).toList(),
                "the new issue TSMC is linked to, and TSMC's new relation to it");
        assertEquals(List.of(TSMC), tsmc.items().get(1).companyIds());
        assertTrue(tool().read(SCOPE, new ChatToolRequest("graph.version.diff", List.of("KRX:005930"), 20)).items()
                .isEmpty(), "Samsung's relations did not change");
        assertEquals(List.of(AI_ACCEL), tool().read(SCOPE, new ChatToolRequest("graph.version.diff", List.of(AI_ACCEL),
                20)).items().stream().map(ChatToolItem::id).toList());
    }

    @Test
    void evidenceIsWhatIsReadableNowWithinTheLimitAndAnExcludedIssueIsNoAddition() {
        var all = tool().read(SCOPE, whole(null));
        String first = all.evidenceIds().getFirst();
        denied.add(first);
        assertFalse(tool().read(SCOPE, whole(null)).evidenceIds().contains(first));

        var cut = tool().read(SCOPE, new ChatToolRequest("graph.version.diff", List.of(ChatCapability.WHOLE_GRAPH), 1));
        assertEquals(1, cut.evidenceIds().size());
        assertTrue(cut.truncated());

        exclusions = new DisclosureExclusions(1, Set.of(AI_ACCEL), Set.of(), Set.of());
        assertTrue(tool().read(SCOPE, whole(null)).items().stream().noneMatch(i -> i.id().equals(AI_ACCEL)),
                "the current exclusions apply to both maps");
    }

    @Test
    void aMapThatCannotBeReadIsUnavailableNeverNoChange() {
        assertThrows(ChatToolUnavailable.class, () -> tool().read(new ChatToolScope("job-1", null, null), whole(null)));
        assertThrows(ChatToolUnavailable.class,
                () -> tool().read(new ChatToolScope("job-1", "fixture-unknown", null), whole(null)));
    }

    private static ChatToolRequest whole(Instant since) {
        return new ChatToolRequest("graph.version.diff", List.of(ChatCapability.WHOLE_GRAPH), 20, null, since);
    }

    private GraphVersionDiffTool tool() {
        GraphVersionRepository versions = repository();
        var reader = new PublicGraphReader(new GraphVersionSelector(versions, Clock.fixed(NOW, ZoneOffset.UTC)),
                new FixtureGraphSnapshotStore(GraphVersionDiffToolTest.class.getClassLoader()), pinned -> exclusions);
        ChatEvidenceAccess access = new ChatEvidenceAccess() {
            @Override
            public boolean readable(String id, String version, Instant asOf, String requestId) {
                return !denied.contains(id);
            }

            @Override
            public Readability readability(String id, String version, Instant asOf, String requestId) {
                return denied.contains(id) ? Readability.DENIED : Readability.READABLE;
            }
        };
        return new GraphVersionDiffTool(reader, versions, access, Clock.fixed(NOW, ZoneOffset.UTC));
    }

    /** 10-01 public from 2026-10-01, 10-08 from 2026-10-08 (after 10-01). */
    private static GraphVersionRepository repository() {
        Map<String, GraphVersionRecord> known = Map.of(OLD, record(OLD, false), ACTIVE, record(ACTIVE, true));
        return new GraphVersionRepository() {
            public Optional<GraphVersionRecord> find(String id) { return Optional.ofNullable(known.get(id)); }
            public Optional<GraphVersionRecord> active() { return Optional.of(known.get(ACTIVE)); }
            public Optional<String> activeVersionIdAt(Instant asOf) {
                if (asOf.isBefore(Instant.parse("2026-10-01T00:00:00Z"))) return Optional.empty();
                return Optional.of(asOf.isBefore(Instant.parse("2026-10-08T00:00:00Z")) ? OLD : ACTIVE);
            }
            public boolean everActivated(String id) { return known.containsKey(id); }
            public Optional<Instant> firstActivatedAt(String id) { return OLD.equals(id) ? Optional.of(Instant.parse("2026-10-01T00:00:00Z")) : ACTIVE.equals(id) ? Optional.of(Instant.parse("2026-10-08T00:00:00Z")) : Optional.empty(); }
            public Optional<String> previousVersionId(String id, Instant at) {
                return ACTIVE.equals(id) ? Optional.of(OLD) : Optional.empty();
            }
        };
    }

    private static GraphVersionRecord record(String id, boolean active) {
        return new GraphVersionRecord(id, 1, "fixture", "artifact-" + id, FixtureGraphSnapshotStore.URI_PREFIX + id + ".json",
                FixtureGraphSnapshotStore.sha256(bytes(id)), active);
    }

    private static byte[] bytes(String id) {
        try (InputStream in = GraphVersionDiffToolTest.class.getClassLoader()
                .getResourceAsStream("graph-fixtures/" + id + ".json")) {
            return in.readAllBytes();
        } catch (IOException exception) {
            throw new UncheckedIOException(exception);
        }
    }
}
