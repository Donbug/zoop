package com.zoop.graph.read;

import com.zoop.graph.snapshot.FixtureGraphSnapshotStore;
import com.zoop.graph.snapshot.GraphSnapshotCodec;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import com.zoop.graph.version.GraphVersionRecord;
import com.zoop.graph.version.GraphVersionRepository;
import com.zoop.graph.version.GraphVersionSelector;
import java.io.IOException;
import java.io.InputStream;
import java.io.UncheckedIOException;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Map;
import java.util.Optional;

final class GraphReadFixtures {
    static final String NVDA = "NASDAQ:NVDA";
    static final String HYNIX = "KRX:000660";
    static final String HANMI = "KRX:042700";
    static final String HBM_SUPPLY = "iss-fixture-hbm-supply";
    static final String HBM_EQUIP = "iss-fixture-hbm-equip";
    static final String AI_ACCEL = "iss-fixture-ai-accel";

    private GraphReadFixtures() {
    }

    static byte[] bytes(String versionId) {
        try (InputStream in = GraphReadFixtures.class.getClassLoader()
                .getResourceAsStream("graph-fixtures/" + versionId + ".json")) {
            return in.readAllBytes();
        } catch (IOException exception) {
            throw new UncheckedIOException(exception);
        }
    }

    static PublicGraphSnapshot snapshot(String versionId) {
        return GraphSnapshotCodec.read(bytes(versionId), versionId);
    }

    static GraphVersionRecord record(String id, boolean active) {
        return new GraphVersionRecord(id, 1, "fixture", "artifact-" + id, FixtureGraphSnapshotStore.URI_PREFIX + id + ".json",
                FixtureGraphSnapshotStore.sha256(bytes(id)), active);
    }

    /** Both fixtures, activated at 2026-10-01 and 2026-10-08 like graph-fixtures/index.json; 10-08 is active. */
    static GraphVersionRepository repository() {
        Map<String, GraphVersionRecord> versions = Map.of("fixture-2026-10-01", record("fixture-2026-10-01", false),
                "fixture-2026-10-08", record("fixture-2026-10-08", true));
        return new GraphVersionRepository() {
            public Optional<GraphVersionRecord> find(String id) { return Optional.ofNullable(versions.get(id)); }
            public Optional<GraphVersionRecord> active() { return Optional.of(versions.get("fixture-2026-10-08")); }
            public Optional<String> activeVersionIdAt(Instant asOf) {
                if (asOf.isBefore(Instant.parse("2026-10-01T00:00:00Z"))) return Optional.empty();
                return Optional.of(asOf.isBefore(Instant.parse("2026-10-08T00:00:00Z")) ? "fixture-2026-10-01" : "fixture-2026-10-08");
            }
            public boolean everActivated(String id) { return versions.containsKey(id); }
            public Optional<Instant> firstActivatedAt(String id) {
                // The fixture activation history: each fixture became active on its own date.
                return versions.containsKey(id) ? Optional.of(Instant.parse(id.substring("fixture-".length()) + "T00:00:00Z"))
                        : Optional.empty();
            }
        };
    }

    /** The active fixture with its first article's publication time unknown: a read as of its first activation drops it. */
    static com.zoop.graph.snapshot.PublicGraphSnapshot withAnUndatedArticle() {
        var base = snapshot("fixture-2026-10-08");
        var articles = base.articles().stream().map(a -> a == base.articles().getFirst()
                ? new PublicGraphSnapshot.Article(a.articleId(), a.version(), a.title(), a.url(), null) : a).toList();
        return new PublicGraphSnapshot(base.snapshotFormat(), base.versionId(), base.sourceBundleId(), base.companies(),
                base.issues(), base.relations(), articles, base.evidence());
    }

    /** A reader over {@link #withAnUndatedArticle} for every version, at a fixed request time. */
    static PublicGraphReader undatedReader(Instant now) {
        var snapshot = withAnUndatedArticle();
        return new PublicGraphReader(new GraphVersionSelector(repository(), Clock.fixed(now, ZoneOffset.UTC)),
                version -> snapshot, pinned -> DisclosureExclusions.NONE);
    }

    static PublicGraphReader reader(Instant now, DisclosureExclusionReader exclusions) {
        return new PublicGraphReader(new GraphVersionSelector(repository(), Clock.fixed(now, ZoneOffset.UTC)),
                new FixtureGraphSnapshotStore(GraphReadFixtures.class.getClassLoader()), exclusions);
    }
}
