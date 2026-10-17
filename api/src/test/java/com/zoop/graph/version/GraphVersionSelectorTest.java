package com.zoop.graph.version;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class GraphVersionSelectorTest {
    private static final Instant NOW = Instant.parse("2026-10-16T12:00:00Z");
    private final InMemoryRepository repository = new InMemoryRepository();
    private final GraphVersionSelector selector = new GraphVersionSelector(repository, Clock.fixed(NOW, ZoneOffset.UTC));

    @BeforeEach
    void history() {
        repository.register("v1");
        repository.register("v2");
        repository.register("registered-only");
        repository.activate("v1", Instant.parse("2026-10-01T00:00:00Z"));
        repository.activate("v2", Instant.parse("2026-10-08T00:00:00Z"));
    }

    private ErrorCode failure(String round, String graphVersion, Instant asOf) {
        return assertThrows(CustomException.class, () -> selector.select(round, graphVersion, asOf)).getErrorCode();
    }

    @Test
    void withoutSelectorsTheCurrentPointerIsPinnedAtRequestStart() {
        SelectedGraphVersion selected = selector.select(null, null, null);
        assertEquals("v2", selected.version().id());
        assertEquals(NOW, selected.asOf());
        assertFalse(selected.asOfRequested());
    }

    @Test
    void asOfPicksTheVersionActiveAtThatTime() {
        SelectedGraphVersion selected = selector.select(null, null, Instant.parse("2026-10-05T00:00:00Z"));
        assertEquals("v1", selected.version().id());
        assertTrue(selected.asOfRequested());
        assertEquals("v2", selector.select(null, null, Instant.parse("2026-10-08T00:00:00Z")).version().id());
    }

    @Test
    void asOfBeforeAnyActivationIsUnavailableNotTheNewestGraph() {
        assertEquals(ErrorCode.VERSION_UNAVAILABLE, failure(null, null, Instant.parse("2026-09-30T23:59:59Z")));
    }

    @Test
    void graphVersionMustAgreeWithAsOf() {
        assertEquals("v1", selector.select(null, "v1", Instant.parse("2026-10-05T00:00:00Z")).version().id());
        assertEquals(ErrorCode.INVALID_REQUEST, failure(null, "v2", Instant.parse("2026-10-05T00:00:00Z")));
    }

    @Test
    void pastActiveVersionStaysReadableByIdButRegisteredOnlyVersionDoesNot() {
        assertEquals("v1", selector.select(null, "v1", null).version().id());
        assertEquals(ErrorCode.VERSION_UNAVAILABLE, failure(null, "registered-only", null));
        assertEquals(ErrorCode.VERSION_UNAVAILABLE, failure(null, "unknown", null));
    }

    @Test
    void malformedVersionIdIsInvalid() {
        assertEquals(ErrorCode.INVALID_REQUEST, failure(null, "bad id/..", null));
    }

    @Test
    void roundWithoutAPinnedRoundVersionIsUnavailable() {
        assertEquals(ErrorCode.VERSION_UNAVAILABLE, failure("brf-2026-10-16-morning", null, null));
    }

    @Test
    void noActiveVersionIsUnavailable() {
        InMemoryRepository empty = new InMemoryRepository();
        var emptySelector = new GraphVersionSelector(empty, Clock.fixed(NOW, ZoneOffset.UTC));
        assertEquals(ErrorCode.VERSION_UNAVAILABLE,
                assertThrows(CustomException.class, () -> emptySelector.select(null, null, null)).getErrorCode());
    }

    /** Mirrors the SQL ordering of JdbcGraphVersionRepository: (activated_at DESC, id DESC), pointer changes only. */
    static final class InMemoryRepository implements GraphVersionRepository {
        private final Map<String, GraphVersionRecord> versions = new HashMap<>();
        private final List<Object[]> activations = new ArrayList<>();
        private String active;

        void register(String id) {
            versions.put(id, new GraphVersionRecord(id, versions.size() + 1, "fixture", "artifact-" + id,
                    "classpath:graph-fixtures/" + id + ".json", "0".repeat(64), false));
        }

        void activate(String id, Instant at) {
            activations.add(new Object[] {activations.size() + 1L, id, at});
            active = id;
        }

        @Override
        public Optional<GraphVersionRecord> find(String versionId) {
            return Optional.ofNullable(versions.get(versionId));
        }

        @Override
        public Optional<GraphVersionRecord> active() {
            return Optional.ofNullable(active).map(versions::get);
        }

        @Override
        public Optional<String> activeVersionIdAt(Instant asOf) {
            return activations.stream().filter(a -> !((Instant) a[2]).isAfter(asOf))
                    .max(Comparator.<Object[], Instant>comparing(a -> (Instant) a[2]).thenComparing(a -> (Long) a[0]))
                    .map(a -> (String) a[1]);
        }

        @Override
        public boolean everActivated(String versionId) {
            return activations.stream().anyMatch(a -> a[1].equals(versionId));
        }
    }
}
