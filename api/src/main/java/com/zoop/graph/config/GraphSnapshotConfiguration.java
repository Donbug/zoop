package com.zoop.graph.config;

import com.zoop.graph.read.DisclosureExclusionReader;
import com.zoop.graph.read.DisclosureExclusions;
import com.zoop.graph.snapshot.FixtureGraphSnapshotStore;
import com.zoop.graph.snapshot.FixtureGraphVersionSeeder;
import com.zoop.graph.snapshot.GraphSnapshotStore;
import com.zoop.graph.snapshot.GraphSnapshotUnavailableException;
import com.zoop.graph.version.JdbcGraphVersionRepository;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Chooses the snapshot source with {@code zoop.graph.snapshot.source}: {@code none} (default) or {@code fixture}
 * (local/dev synthetic data). The imported-artifact source is added later behind the same port.
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

    /** No exclusion store exists yet (FS081 slice); nothing is excluded until it does. */
    @Bean
    @ConditionalOnMissingBean(DisclosureExclusionReader.class)
    DisclosureExclusionReader noDisclosureExclusions() {
        return () -> DisclosureExclusions.NONE;
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
