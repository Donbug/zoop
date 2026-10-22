package com.zoop.graph.config;

import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.artifact.storage.ArtifactStoreException;
import com.zoop.document.repository.DocumentRegistryRepository;
import com.zoop.graph.read.DisclosureExclusionReader;
import com.zoop.graph.read.DisclosureExclusions;
import com.zoop.graph.snapshot.ArtifactGraphSnapshotStore;
import com.zoop.graph.snapshot.FixtureGraphSnapshotStore;
import com.zoop.graph.snapshot.FixtureGraphVersionSeeder;
import com.zoop.graph.snapshot.GraphSnapshotStore;
import com.zoop.graph.snapshot.GraphSnapshotUnavailableException;
import com.zoop.graph.version.JdbcGraphVersionRepository;
import java.nio.file.InvalidPathException;
import java.nio.file.Path;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Chooses the snapshot source with {@code zoop.graph.snapshot.source}: {@code none} (default), {@code fixture} (local/dev
 * synthetic data) or {@code artifact} (snapshots staged by the operator graph handoff import, read from
 * {@code zoop.graph.snapshot.artifact-root}).
 */
@Configuration(proxyBeanMethods = false)
public class GraphSnapshotConfiguration {

    @Configuration(proxyBeanMethods = false)
    @ConditionalOnProperty(prefix = "zoop.graph.snapshot", name = "source", havingValue = "fixture")
    static class Fixture {
        @Bean
        FixtureGraphSnapshotStore fixtureGraphSnapshotStore() {
            return new FixtureGraphSnapshotStore(GraphSnapshotConfiguration.class.getClassLoader());
        }

        @Bean
        FixtureGraphVersionSeeder fixtureGraphVersionSeeder(JdbcGraphVersionRepository repository,
                FixtureGraphSnapshotStore store) {
            return new FixtureGraphVersionSeeder(repository, store);
        }
    }

    /**
     * Imported snapshots: read-only and verified against the artifact registry on every load. Never seeds, registers or activates
     * anything; which version the public API shows stays the activation pointer's decision.
     */
    @Configuration(proxyBeanMethods = false)
    @ConditionalOnProperty(prefix = "zoop.graph.snapshot", name = "source", havingValue = "artifact")
    static class Artifact {
        @Bean
        ArtifactGraphSnapshotStore artifactGraphSnapshotStore(
                @Value("${zoop.graph.snapshot.artifact-root:}") String artifactRoot, DocumentRegistryRepository registry) {
            if (artifactRoot == null || artifactRoot.isBlank()) {
                throw new IllegalStateException("zoop.graph.snapshot.artifact-root must be set when source=artifact");
            }
            try {
                Path root = Path.of(artifactRoot);
                if (!root.isAbsolute() || !root.equals(root.normalize())) {
                    throw new IllegalStateException("zoop.graph.snapshot.artifact-root must be a normalized absolute path");
                }
                return new ArtifactGraphSnapshotStore(ArtifactFileStore.at(root), registry,
                        new FixtureGraphSnapshotStore(GraphSnapshotConfiguration.class.getClassLoader()));
            } catch (InvalidPathException error) {
                throw new IllegalStateException("zoop.graph.snapshot.artifact-root must be a valid path");
            } catch (ArtifactStoreException error) {
                throw new IllegalStateException("zoop.graph.snapshot.artifact-root cannot be used as an artifact store");
            }
        }
    }

    /** No exclusion store exists yet (FS081 slice); nothing is excluded until it does. */
    @Bean
    @ConditionalOnMissingBean(DisclosureExclusionReader.class)
    DisclosureExclusionReader noDisclosureExclusions() {
        return new DisclosureExclusionReader() {
            @Override
            public DisclosureExclusions current() {
                return DisclosureExclusions.NONE;
            }

            @Override
            public boolean authoritative() {
                return false;
            }
        };
    }

    /** No source configured: a registered version cannot be read, which is 503 and never an empty graph. */
    @Bean
    @ConditionalOnMissingBean(GraphSnapshotStore.class)
    GraphSnapshotStore unavailableGraphSnapshotStore() {
        return version -> {
            throw new GraphSnapshotUnavailableException("snapshot_source_disabled");
        };
    }
}
