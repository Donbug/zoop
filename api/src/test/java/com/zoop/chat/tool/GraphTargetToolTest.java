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

import com.zoop.chat.service.ChatCompanyProfiles;
import com.zoop.chat.service.ChatEvidenceAccess;
import com.zoop.document.evidence.service.EvidenceService.Readability;
import com.zoop.graph.read.DisclosureExclusions;
import com.zoop.graph.read.PublicGraphReader;
import com.zoop.graph.snapshot.FixtureGraphSnapshotStore;
import com.zoop.graph.version.GraphVersionRecord;
import com.zoop.graph.version.GraphVersionRepository;
import com.zoop.graph.version.GraphVersionSelector;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.transaction.CannotCreateTransactionException;

import static org.junit.jupiter.api.Assertions.*;

/** D-AI-02 reads: company.read, issue.read and evidence.resolve over the synthetic public graph fixtures. */
class GraphTargetToolTest {
    private static final Instant NOW = Instant.parse("2026-10-21T03:00:00Z");
    private static final String OLD = "fixture-2026-10-01";
    private static final String ACTIVE = "fixture-2026-10-08";
    private static final String HYNIX = "KRX:000660";
    private static final String NVDA = "NASDAQ:NVDA";
    private static final String HBM_SUPPLY = "iss-fixture-hbm-supply";
    private static final String SUPPLY_NVDA = "ev-912843a071ee90c12ee7e909c65f06ce748d2a35c7c29c6c871faac130e4f395";
    private static final String SUPPLY_HYNIX = "ev-bb3008cb36e9b51c0d2fd77af059259332b1887cc04862e185a496c3dcc9e421";
    private static final String EQUIP_HYNIX = "ev-fd9d18853fde470f24184b7db11e534270c580072fc0ca877323825a751c94bf";
    private static final ChatToolScope SCOPE = new ChatToolScope("job-1", ACTIVE, null);

    private final Set<String> denied = new HashSet<>();
    private final Set<String> unchecked = new HashSet<>();
    private final List<String> checks = new ArrayList<>();
    private final Map<String, ChatCompanyProfiles.Quote> profiles = new java.util.HashMap<>();
    private DisclosureExclusions exclusions = DisclosureExclusions.NONE;

    @Test
    void companyReadReturnsTheVisibleCompanyAndItsReadableRelationEvidence() {
        var out = company().read(SCOPE, new ChatToolRequest("company.read", List.of(HYNIX, "KRX:999999", HBM_SUPPLY), 20));
        assertEquals(ACTIVE, out.dataVersion());
        assertEquals(1, out.items().size(), "an unknown id and an issue id are not companies");
        var hynix = out.items().getFirst();
        assertEquals(new ChatToolItem(HYNIX, "company", "SK하이닉스", List.of(HYNIX), hynix.evidenceIds()), hynix);
        assertEquals(Set.of(SUPPLY_HYNIX, EQUIP_HYNIX), Set.copyOf(hynix.evidenceIds()));
        assertEquals(Set.copyOf(hynix.evidenceIds()), Set.copyOf(out.evidenceIds()));
        assertFalse(out.truncated());
        assertFalse(out.nextAllowed());
    }

    @Test
    void companyReadPassesTheCatalogProfileAheadOfRelationEvidence() {
        String profile = "ev-" + "a".repeat(64);
        profiles.put(HYNIX, new ChatCompanyProfiles.Quote(profile, HYNIX, "SK하이닉스", "SK하이닉스 사업 개요: 메모리", null,
                null));
        var out = company().read(SCOPE, new ChatToolRequest("company.read", List.of(HYNIX), 20));
        assertEquals(profile, out.items().getFirst().evidenceIds().getFirst());
        assertEquals(Set.of(profile, SUPPLY_HYNIX, EQUIP_HYNIX), Set.copyOf(out.evidenceIds()));

        denied.add(profile);
        var refused = company().read(SCOPE, new ChatToolRequest("company.read", List.of(HYNIX), 20));
        assertFalse(refused.evidenceIds().contains(profile), "a profile is passed on only through the evidence access");
    }

    @Test
    void aProfileIsReadableOnlyWhileItsCompanyIsVisibleAndItsTextUnchangedSinceTheAsOf() {
        Instant updated = Instant.parse("2026-10-05T00:00:00Z");
        var hynix = new ChatCompanyProfiles.Quote("ev-" + "a".repeat(64), HYNIX, "SK하이닉스", "SK하이닉스 사업 개요: 메모리",
                null, updated);
        var catalog = profiles();
        assertEquals(Readability.READABLE, catalog.readability(hynix, ACTIVE, null, "job-1"));
        assertEquals(Readability.READABLE, catalog.readability(hynix, ACTIVE, Instant.parse("2026-10-09T00:00:00Z"), "job-1"));
        assertEquals(Readability.DENIED, catalog.readability(hynix, ACTIVE, Instant.parse("2026-10-04T00:00:00Z"), "job-1"),
                "the catalog changed after that asOf: its current text is not what it said then");
        assertEquals(Readability.DENIED, catalog.readability(hynix, null, null, "job-1"));

        var unlisted = new ChatCompanyProfiles.Quote("ev-" + "b".repeat(64), "KRX:999999", "없는 기업", "없는 기업 사업 개요: -",
                null, updated);
        assertEquals(Readability.DENIED, catalog.readability(unlisted, ACTIVE, null, "job-1"),
                "a catalog text alone never makes a company public");

        var outage = new ChatCompanyProfiles(null, null, failingReader(new DataAccessResourceFailureException("down")));
        assertEquals(Readability.UNAVAILABLE, outage.readability(hynix, ACTIVE, null, "job-1"));
        assertEquals(Readability.UNAVAILABLE, profiles().readability(hynix, "fixture-unknown", null, "job-1"));
    }

    @Test
    void aCatalogOutageWhileCheckingAnIdIsUnavailableNotAFault() {
        for (RuntimeException failure : List.of(new DataAccessResourceFailureException("companies unreachable"),
                new CannotCreateTransactionException("no connection"))) {
            var catalog = new ChatCompanyProfiles(null, null, reader()) {
                @Override
                public Optional<Quote> byId(String evidenceId) {
                    throw failure;
                }
            };
            assertEquals(Optional.of(Readability.UNAVAILABLE), catalog.check("ev-" + "a".repeat(64), ACTIVE, null, "job-1"));
        }
    }

    @Test
    void issueReadReturnsItsCompaniesAndEvidence() {
        var out = issue().read(SCOPE, new ChatToolRequest("issue.read", List.of(HBM_SUPPLY, HYNIX), 20));
        assertEquals(1, out.items().size());
        var issue = out.items().getFirst();
        assertEquals("issue", issue.kind());
        assertEquals(Set.of(NVDA, HYNIX), Set.copyOf(issue.companyIds()));
        assertEquals(Set.of(SUPPLY_NVDA, SUPPLY_HYNIX), Set.copyOf(issue.evidenceIds()));
    }

    @Test
    void theLimitCutsEvidenceAndSaysSoInsteadOfReportingNone() {
        var out = company().read(SCOPE, new ChatToolRequest("company.read", List.of(HYNIX), 1));
        assertEquals(1, out.evidenceIds().size());
        assertTrue(out.truncated());
        assertEquals(out.evidenceIds(), out.items().getFirst().evidenceIds());
    }

    @Test
    void theLimitIsSharedByAllTargetsInTargetOrder() {
        var out = issue().read(SCOPE, new ChatToolRequest("issue.read", List.of(HBM_SUPPLY, "iss-fixture-hbm-equip"), 2));
        assertEquals(2, out.items().size());
        assertEquals(out.items().getFirst().evidenceIds(), out.evidenceIds(), "the first issue used the whole limit");
        assertEquals(List.of(), out.items().get(1).evidenceIds());
        assertTrue(out.truncated());
        assertEquals(2, checks.size(), "evidence past the limit is not read");
    }

    @Test
    void evidenceTheReadRefusesIsNotPassedOnAndAnUnreadableSpanIsNotFound() {
        denied.add(SUPPLY_HYNIX);
        var out = company().read(SCOPE, new ChatToolRequest("company.read", List.of(HYNIX), 20));
        assertEquals(List.of(EQUIP_HYNIX), out.evidenceIds());
        assertFalse(out.truncated());

        var resolved = evidence().read(SCOPE, new ChatToolRequest("evidence.resolve",
                List.of(SUPPLY_HYNIX, EQUIP_HYNIX, HYNIX), 20));
        assertEquals(List.of(EQUIP_HYNIX), resolved.items().stream().map(ChatToolItem::id).toList());
        assertEquals("evidence", resolved.items().getFirst().kind());
        assertEquals(List.of(EQUIP_HYNIX), resolved.evidenceIds());
    }

    @Test
    void anEvidenceStateThatCannotBeCheckedFailsTheCall() {
        unchecked.add(SUPPLY_HYNIX);
        assertThrows(ChatToolUnavailable.class,
                () -> company().read(SCOPE, new ChatToolRequest("company.read", List.of(HYNIX), 20)));
    }

    @Test
    void withoutAReadableGraphTheCallFailsInsteadOfFindingNothing() {
        var request = new ChatToolRequest("company.read", List.of(HYNIX), 20);
        assertThrows(ChatToolUnavailable.class, () -> company().read(new ChatToolScope("job-1", null, null), request));
        assertThrows(ChatToolUnavailable.class,
                () -> company().read(new ChatToolScope("job-1", "fixture-unknown", null), request));
    }

    @Test
    void aDatabaseOutageIsUnavailableButAnyOtherErrorStaysAFault() {
        var request = new ChatToolRequest("company.read", List.of(HYNIX), 20);
        for (RuntimeException failure : List.of(new DataAccessResourceFailureException("graph_versions unreachable"),
                new CannotCreateTransactionException("no connection"))) {
            var tool = new CompanyReadTool(failingReader(failure), access(), profiles());
            assertThrows(ChatToolUnavailable.class, () -> tool.read(SCOPE, request));
        }
        var bug = new CompanyReadTool(failingReader(new IllegalStateException("bug")), access(), profiles());
        assertThrows(IllegalStateException.class, () -> bug.read(SCOPE, request));
    }

    @Test
    void readsUseThePinnedVersionAsOfAndCurrentExclusions() {
        Instant asOf = Instant.parse("2026-10-09T00:00:00Z");
        company().read(new ChatToolScope("job-1", ACTIVE, asOf), new ChatToolRequest("company.read", List.of(HYNIX), 20));
        assertFalse(checks.isEmpty());
        assertTrue(checks.stream().allMatch(c -> c.endsWith("@" + ACTIVE + "@" + asOf)), checks.toString());

        exclusions = new DisclosureExclusions(1, Set.of(HBM_SUPPLY), Set.of(), Set.of());
        assertTrue(issue().read(SCOPE, new ChatToolRequest("issue.read", List.of(HBM_SUPPLY), 20)).items().isEmpty());
    }

    @Test
    void theRegistryBindsOnlyTheImplementedReads() {
        var registry = new ChatToolRegistry(List.of(company(), issue(), evidence()));
        assertEquals(Set.of("company.read", "issue.read", "evidence.resolve"), registry.bound());
        assertTrue(registry.bind("graph.path.read").isEmpty());
        assertEquals("zoop-core-read", registry.bind("evidence.resolve").orElseThrow().capability().group());
        assertThrows(IllegalStateException.class, () -> new ChatToolRegistry(List.of(company(), company())));
    }

    private CompanyReadTool company() {
        return new CompanyReadTool(reader(), access(), profiles());
    }

    private ChatCompanyProfiles profiles() {
        return new ChatCompanyProfiles(null, null, reader()) {
            @Override
            public Optional<Quote> forCompany(String companyId) {
                return Optional.ofNullable(profiles.get(companyId));
            }
        };
    }

    private IssueReadTool issue() {
        return new IssueReadTool(reader(), access());
    }

    private EvidenceResolveTool evidence() {
        return new EvidenceResolveTool(reader(), access());
    }

    private PublicGraphReader reader() {
        var selector = new GraphVersionSelector(repository(), Clock.fixed(NOW, ZoneOffset.UTC));
        return new PublicGraphReader(selector, new FixtureGraphSnapshotStore(GraphTargetToolTest.class.getClassLoader()),
                pinned -> exclusions);
    }

    private PublicGraphReader failingReader(RuntimeException failure) {
        GraphVersionRepository failing = new GraphVersionRepository() {
            public Optional<GraphVersionRecord> find(String id) { throw failure; }
            public Optional<GraphVersionRecord> active() { throw failure; }
            public Optional<String> activeVersionIdAt(Instant asOf) { throw failure; }
            public boolean everActivated(String id) { throw failure; }
        };
        return new PublicGraphReader(new GraphVersionSelector(failing, Clock.fixed(NOW, ZoneOffset.UTC)),
                new FixtureGraphSnapshotStore(GraphTargetToolTest.class.getClassLoader()), pinned -> exclusions);
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

    /** Both fixtures, activated at 2026-10-01 and 2026-10-08. */
    private static GraphVersionRepository repository() {
        Map<String, GraphVersionRecord> known = Map.of(OLD, record(OLD, false), ACTIVE, record(ACTIVE, true));
        return new GraphVersionRepository() {
            public Optional<GraphVersionRecord> find(String id) { return Optional.ofNullable(known.get(id)); }
            public Optional<GraphVersionRecord> active() { return Optional.ofNullable(known.get(ACTIVE)); }
            public Optional<String> activeVersionIdAt(Instant asOf) {
                if (asOf.isBefore(Instant.parse("2026-10-01T00:00:00Z"))) return Optional.empty();
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
        try (InputStream in = GraphTargetToolTest.class.getClassLoader()
                .getResourceAsStream("graph-fixtures/" + id + ".json")) {
            return in.readAllBytes();
        } catch (IOException exception) {
            throw new UncheckedIOException(exception);
        }
    }
}
