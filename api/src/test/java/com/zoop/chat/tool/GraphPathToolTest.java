package com.zoop.chat.tool;

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
import com.zoop.chat.service.ChatEvidenceAccess;
import com.zoop.document.evidence.service.EvidenceService.Readability;
import com.zoop.graph.read.DisclosureExclusions;
import com.zoop.graph.read.GraphPathLookup;
import com.zoop.graph.read.PublicGraphReader;
import com.zoop.graph.snapshot.FixtureGraphSnapshotStore;
import com.zoop.graph.version.GraphVersionRecord;
import com.zoop.graph.version.GraphVersionRepository;
import com.zoop.graph.version.GraphVersionSelector;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

/**
 * D-AI-02 Q04 reads: graph.path.read over the synthetic public graph fixture. The fixture has two separate parts: NVIDIA and
 * SK hynix share the HBM supply issue, Hanmi Semiconductor and SK hynix the HBM equipment issue, which follows the supply
 * issue; ASML, TSMC and Samsung share the EUV export issue, and TSMC and AMD the AI accelerator issue. A hop is the map's
 * depth hop: company – issue – company.
 */
class GraphPathToolTest {
    private static final Instant NOW = Instant.parse("2026-10-21T03:00:00Z");
    private static final String ACTIVE = "fixture-2026-10-08";
    private static final String SAMSUNG = "KRX:005930";
    private static final String HYNIX = "KRX:000660";
    private static final String NVDA = "NASDAQ:NVDA";
    private static final String HANMI = "KRX:042700";
    private static final String AMD = "NASDAQ:AMD";
    private static final String HBM_SUPPLY = "iss-fixture-hbm-supply";
    private static final String HBM_EQUIP = "iss-fixture-hbm-equip";
    private static final ChatToolScope SCOPE = new ChatToolScope("job-1", ACTIVE, null);

    private final Set<String> denied = new HashSet<>();
    private final Set<String> unchecked = new HashSet<>();
    private final List<String> checks = new ArrayList<>();

    private static ChatToolRequest request(int limit, String... targets) {
        return new ChatToolRequest("graph.path.read", List.of(targets), limit);
    }

    private static List<String> ids(ChatToolOutput out, String kind) {
        return out.items().stream().filter(i -> kind.equals(i.kind())).map(ChatToolItem::id).toList();
    }

    @Test
    void theShortestConnectionIsThePathOfStoredEdgesInOrder() {
        var out = tool().read(SCOPE, request(20, NVDA, HANMI));
        assertEquals(ACTIVE, out.dataVersion());
        // Two hops like the map's depth: NVIDIA – HBM supply – SK hynix – HBM equipment – Hanmi. The "follows" link between
        // the two issues is not a step, as in a map read with a depth.
        assertEquals(List.of(NVDA, HBM_SUPPLY, HYNIX, HBM_EQUIP, HANMI),
                out.items().stream().filter(i -> !"edge".equals(i.kind())).map(ChatToolItem::id).toList());
        assertEquals(4, ids(out, "edge").size());
        assertEquals(Set.of(NVDA, HYNIX, HANMI), Set.copyOf(ids(out, "company")));
        assertFalse(out.truncated());
        assertFalse(out.nextAllowed());
        // The relation evidence of each edge, edges first in path order.
        List<String> edgeEvidence = out.items().stream().filter(i -> "edge".equals(i.kind()))
                .flatMap(i -> i.evidenceIds().stream()).distinct().toList();
        assertEquals(4, edgeEvidence.size());
        assertEquals(edgeEvidence, out.evidenceIds().subList(0, edgeEvidence.size()));
        assertEquals(Set.copyOf(out.evidenceIds()), out.items().stream().flatMap(i -> i.evidenceIds().stream())
                .collect(java.util.stream.Collectors.toSet()));
    }

    @Test
    void theSamePathIsFoundEveryTime() {
        var first = tool().read(SCOPE, request(20, HYNIX, NVDA));
        var second = tool().read(SCOPE, request(20, HYNIX, NVDA));
        assertEquals(first, second);
        assertEquals(List.of(HYNIX, HBM_SUPPLY, NVDA),
                first.items().stream().filter(i -> !"edge".equals(i.kind())).map(ChatToolItem::id).toList());
    }

    @Test
    void provenUnconnectedTargetsGiveAnEmptyResultThatIsNotCut() {
        var out = tool().read(SCOPE, request(20, NVDA, SAMSUNG));
        assertTrue(out.items().isEmpty(), "the two parts of the graph do not touch");
        assertTrue(out.evidenceIds().isEmpty());
        assertFalse(out.truncated(), "nothing was cut, so the answer may say no connection was found");
    }

    @Test
    void aSearchThatReachesTheHopLimitIsCutNeverNone() {
        var graph = reader().read(null, ACTIVE, null).graph();
        var paths = new GraphPathLookup(graph);
        // Samsung – EUV export – TSMC – AI accelerator – AMD is two hops.
        assertEquals(GraphPathLookup.Status.FOUND, paths.shortest(SAMSUNG, AMD, 2).status());
        assertEquals(GraphPathLookup.Status.CUT, paths.shortest(SAMSUNG, AMD, 1).status());
        // Within one hop Samsung's part is not fully explored, so NVIDIA's absence is not proven yet.
        assertEquals(GraphPathLookup.Status.CUT, paths.shortest(SAMSUNG, NVDA, 1).status());
        assertEquals(GraphPathLookup.Status.NONE, paths.shortest(SAMSUNG, NVDA, 3).status());
        assertEquals(4, tool().read(SCOPE, request(20, SAMSUNG, AMD)).items().stream()
                .filter(i -> "edge".equals(i.kind())).count());
    }

    @Test
    void theFirstTargetIsConnectedToEachOtherTarget() {
        var out = tool().read(SCOPE, request(20, HYNIX, NVDA, HANMI, SAMSUNG));
        assertTrue(ids(out, "company").containsAll(List.of(HYNIX, NVDA, HANMI)));
        assertFalse(ids(out, "company").contains(SAMSUNG), "an unconnected target adds nothing");
        assertFalse(out.truncated());
    }

    @Test
    void aSingleVisibleTargetIsReturnedWithoutAPathAndAnInvisibleOneIsAbsent() {
        var single = tool().read(SCOPE, request(20, HYNIX, "KRX:999999"));
        assertEquals(List.of(HYNIX), single.items().stream().map(ChatToolItem::id).toList());
        assertTrue(single.evidenceIds().isEmpty());
        assertTrue(tool().read(SCOPE, request(20, "KRX:999999", "KRX:888888")).items().isEmpty());
    }

    @Test
    void evidenceIsCappedAndFilteredWithoutDroppingTheConnection() {
        var capped = tool().read(SCOPE, request(1, NVDA, HANMI));
        assertEquals(1, capped.evidenceIds().size());
        assertTrue(capped.truncated(), "evidence past the limit was not read");
        assertEquals(4, ids(capped, "edge").size());

        var all = tool().read(SCOPE, request(20, NVDA, HANMI));
        denied.add(all.evidenceIds().getFirst());
        var filtered = tool().read(SCOPE, request(20, NVDA, HANMI));
        assertEquals(all.evidenceIds().subList(1, all.evidenceIds().size()), filtered.evidenceIds());
        assertEquals(4, ids(filtered, "edge").size(), "an edge whose evidence is not readable stays, uncited");
    }

    @Test
    void withoutAReadableGraphOrEvidenceStateTheCallFailsInsteadOfFindingNothing() {
        assertThrows(ChatToolUnavailable.class,
                () -> tool().read(new ChatToolScope("job-1", null, null), request(20, NVDA, HYNIX)));
        assertThrows(ChatToolUnavailable.class,
                () -> tool().read(new ChatToolScope("job-1", "fixture-unknown", null), request(20, NVDA, HYNIX)));
        var any = tool().read(SCOPE, request(20, NVDA, HYNIX)).evidenceIds().getFirst();
        unchecked.add(any);
        assertThrows(ChatToolUnavailable.class, () -> tool().read(SCOPE, request(20, NVDA, HYNIX)));
    }

    @Test
    void theRegistryBindsThePathRead() {
        var registry = new ChatToolRegistry(List.of(tool()));
        assertEquals(Set.of("graph.path.read"), registry.bound());
        assertEquals("zoop-graph-read", registry.bind("graph.path.read").orElseThrow().capability().group());
    }

    private GraphPathTool tool() {
        return new GraphPathTool(reader(), access());
    }

    private PublicGraphReader reader() {
        var selector = new GraphVersionSelector(repository(), Clock.fixed(NOW, ZoneOffset.UTC));
        return new PublicGraphReader(selector, new FixtureGraphSnapshotStore(GraphPathToolTest.class.getClassLoader()),
                () -> DisclosureExclusions.NONE);
    }

    private ChatEvidenceAccess access() {
        return new ChatEvidenceAccess() {
            @Override
            public boolean readable(String id, String version, Instant asOf, String requestId) {
                return readability(id, version, asOf, requestId) == Readability.READABLE;
            }

            @Override
            public Readability readability(String id, String version, Instant asOf, String requestId) {
                checks.add(id + "@" + version + "@" + asOf);
                if (unchecked.contains(id)) return Readability.UNAVAILABLE;
                return denied.contains(id) ? Readability.DENIED : Readability.READABLE;
            }
        };
    }

    private static GraphVersionRepository repository() {
        Map<String, GraphVersionRecord> known = Map.of(ACTIVE, record(ACTIVE));
        return new GraphVersionRepository() {
            public Optional<GraphVersionRecord> find(String id) { return Optional.ofNullable(known.get(id)); }
            public Optional<GraphVersionRecord> active() { return Optional.of(known.get(ACTIVE)); }
            public Optional<String> activeVersionIdAt(Instant asOf) { return Optional.of(ACTIVE); }
            public boolean everActivated(String id) { return known.containsKey(id); }
        };
    }

    private static GraphVersionRecord record(String id) {
        return new GraphVersionRecord(id, 1, "fixture", "artifact-" + id, FixtureGraphSnapshotStore.URI_PREFIX + id + ".json",
                FixtureGraphSnapshotStore.sha256(bytes(id)), true);
    }

    private static byte[] bytes(String id) {
        try (InputStream in = GraphPathToolTest.class.getClassLoader().getResourceAsStream("graph-fixtures/" + id + ".json")) {
            return in.readAllBytes();
        } catch (IOException exception) {
            throw new UncheckedIOException(exception);
        }
    }
}
