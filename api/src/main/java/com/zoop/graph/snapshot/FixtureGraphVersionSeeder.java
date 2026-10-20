package com.zoop.graph.snapshot;

import com.zoop.common.json.StrictJson;
import com.zoop.common.json.StrictJson.Obj;
import com.zoop.graph.version.JdbcGraphVersionRepository;
import com.zoop.graph.version.JdbcGraphVersionRepository.NewGraphVersion;
import java.time.Instant;
import java.util.List;
import java.util.Set;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;

/**
 * Registers the synthetic fixture versions listed in {@code graph-fixtures/index.json} at startup, in order, with the
 * listed activation times, so asOf selection has a reproducible history. Idempotent. When the bundled fixtures
 * changed (a new snapshot format, edited synthetic data), the fixture rows are reset and seeded again: the database
 * holds only synthetic fixtures here, so no public history is rewritten. Never enabled by default, and refused on a
 * database that already holds imported (non-fixture) versions.
 */
public class FixtureGraphVersionSeeder implements ApplicationRunner {
    private static final Logger log = LoggerFactory.getLogger(FixtureGraphVersionSeeder.class);

    private final JdbcGraphVersionRepository repository;
    private final FixtureGraphSnapshotStore store;

    public FixtureGraphVersionSeeder(JdbcGraphVersionRepository repository, FixtureGraphSnapshotStore store) {
        this.repository = repository;
        this.store = store;
    }

    @Override
    public void run(ApplicationArguments args) {
        if (repository.hasNonFixtureVersions()) {
            throw new IllegalStateException("zoop.graph.snapshot.source=fixture refuses a database that already has "
                    + "imported graph versions; synthetic fixtures must not become the public version");
        }
        Obj index = StrictJson.parseObject(store.read(FixtureGraphSnapshotStore.URI_PREFIX + "index.json"))
                .exactly(Set.of("fixtureFormat", "versions"));
        List<Obj> entries = index.objects("versions");
        boolean changed = false;
        for (Obj entry : entries) {
            entry.exactly(Set.of("versionId", "file", "activatedAt", "reason"));
            String sha = FixtureGraphSnapshotStore.sha256(store.read(FixtureGraphSnapshotStore.URI_PREFIX + entry.string("file")));
            changed |= repository.find(entry.string("versionId")).map(v -> !v.snapshotSha256().equals(sha)).orElse(false);
        }
        if (changed) log.warn("Bundled graph fixtures changed; reset {} fixture versions", repository.resetFixtures());
        for (Obj entry : entries) {
            String versionId = entry.string("versionId");
            String uri = FixtureGraphSnapshotStore.URI_PREFIX + entry.string("file");
            byte[] bytes = store.read(uri);
            PublicGraphSnapshot snapshot = GraphSnapshotCodec.read(bytes, versionId);
            String sha = FixtureGraphSnapshotStore.sha256(bytes);
            var outcome = repository.registerSystemVersion(new NewGraphVersion(versionId, "fixture",
                    "synthetic fixture " + entry.string("file"), "artifact-" + versionId, uri, sha, bytes.length,
                    snapshot.issues().size(), snapshot.relations().size(), snapshot.articles().size()),
                    entry.string("reason"), Instant.parse(entry.string("activatedAt")));
            log.info("Graph fixture {} {}", versionId, outcome);
        }
    }
}
