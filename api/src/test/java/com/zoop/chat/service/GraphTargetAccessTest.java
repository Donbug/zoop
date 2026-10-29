package com.zoop.chat.service;

import java.io.IOException;
import java.io.InputStream;
import java.io.UncheckedIOException;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

import com.zoop.graph.read.DisclosureExclusions;
import com.zoop.graph.read.PublicGraphReader;
import com.zoop.graph.snapshot.FixtureGraphSnapshotStore;
import com.zoop.graph.version.GraphVersionRecord;
import com.zoop.graph.version.GraphVersionRepository;
import com.zoop.graph.version.GraphVersionSelector;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DataAccessResourceFailureException;

import static org.junit.jupiter.api.Assertions.*;

/** D-AI-02 stored results: applied targets are visible through the same public graph read as the chat tools. */
class GraphTargetAccessTest {
    private static final Instant NOW = Instant.parse("2026-10-21T03:00:00Z");
    private static final String ACTIVE = "fixture-2026-10-08";
    private static final String HYNIX = "KRX:000660";
    private static final String HBM_SUPPLY = "iss-fixture-hbm-supply";

    private static final Instant EARLY = Instant.parse("2026-09-01T00:00:00Z");
    private DisclosureExclusions exclusions = DisclosureExclusions.NONE;

    @Test
    void aCompanyOrIssueIsVisibleUntilExcludedAndAnUnknownIdNever() {
        var access = new GraphTargetAccess(reader(repository()));
        assertEquals(Optional.of(Set.of(HYNIX, HBM_SUPPLY)),
                access.visible(Set.of(HYNIX, HBM_SUPPLY, "KRX:999999"), ACTIVE, null, "req-1"));

        exclusions = new DisclosureExclusions(1, Set.of(HBM_SUPPLY), Set.of(), Set.of());
        assertEquals(Optional.of(Set.of(HYNIX)), access.visible(Set.of(HYNIX, HBM_SUPPLY), ACTIVE, null, "req-2"),
                "an issue excluded after the run is no longer visible at the run's own version");
    }

    @Test
    void aRunFrozenWithoutAnAsOfKeepsItsPinUnfilteredAndOneFrozenAtATimeIsFilteredThere() {
        var access = new GraphTargetAccess(reader(repository()));
        assertEquals(Optional.of(Set.of(HYNIX, HBM_SUPPLY)), access.visible(Set.of(HYNIX, HBM_SUPPLY), ACTIVE, null, "r"),
                "never re-read as a version-only address, which would filter at its first publication");
        assertEquals(Optional.of(Set.of(HYNIX)), access.visible(Set.of(HYNIX, HBM_SUPPLY), ACTIVE, EARLY, "r"),
                "the issue was reported after the frozen time");
    }

    @Test
    void noVersionOrAnUnreadableGraphIsUncheckedNotVisible() {
        assertEquals(Optional.empty(), new GraphTargetAccess(reader(repository())).visible(Set.of(HYNIX), null, null, "r"));
        var down = new DataAccessResourceFailureException("down");
        GraphVersionRepository failing = new GraphVersionRepository() {
            public Optional<GraphVersionRecord> find(String id) { throw down; }
            public Optional<GraphVersionRecord> active() { throw down; }
            public Optional<String> activeVersionIdAt(Instant asOf) { throw down; }
            public boolean everActivated(String id) { throw down; }
            public Optional<Instant> firstActivatedAt(String id) { throw down; }
        };
        assertEquals(Optional.empty(), new GraphTargetAccess(reader(failing)).visible(Set.of(HYNIX), ACTIVE, null, "r"));
    }

    private PublicGraphReader reader(GraphVersionRepository repository) {
        return new PublicGraphReader(new GraphVersionSelector(repository, Clock.fixed(NOW, ZoneOffset.UTC)),
                new FixtureGraphSnapshotStore(GraphTargetAccessTest.class.getClassLoader()), pinned -> exclusions);
    }

    private static GraphVersionRepository repository() {
        Map<String, GraphVersionRecord> known = Map.of(ACTIVE, record(ACTIVE));
        return new GraphVersionRepository() {
            public Optional<GraphVersionRecord> find(String id) { return Optional.ofNullable(known.get(id)); }
            public Optional<GraphVersionRecord> active() { return Optional.ofNullable(known.get(ACTIVE)); }
            public Optional<String> activeVersionIdAt(Instant asOf) { return Optional.of(ACTIVE); }
            public boolean everActivated(String id) { return known.containsKey(id); }
            // First published before any fixture issue was reported: a version-only read of it would show none (#88).
            public Optional<Instant> firstActivatedAt(String id) { return everActivated(id) ? Optional.of(EARLY) : Optional.empty(); }
        };
    }

    private static GraphVersionRecord record(String id) {
        return new GraphVersionRecord(id, 1, "fixture", "artifact-" + id, FixtureGraphSnapshotStore.URI_PREFIX + id + ".json",
                FixtureGraphSnapshotStore.sha256(bytes(id)), true);
    }

    private static byte[] bytes(String id) {
        try (InputStream in = GraphTargetAccessTest.class.getClassLoader()
                .getResourceAsStream("graph-fixtures/" + id + ".json")) {
            return in.readAllBytes();
        } catch (IOException exception) {
            throw new UncheckedIOException(exception);
        }
    }
}
