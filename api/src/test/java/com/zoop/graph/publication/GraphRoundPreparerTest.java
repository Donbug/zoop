package com.zoop.graph.publication;

import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import com.zoop.document.evidence.config.DocumentReadProperties;
import com.zoop.graph.publication.JdbcGraphPublicationPreparationRepository.Preparation;
import com.zoop.graph.round.GraphRoundConfigurationException;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.mock.env.MockEnvironment;
import static org.junit.jupiter.api.Assertions.*;

/** The round path preparation's own rules (#55 PR-P3): which attempt is still unknown, and the startup refusals. */
class GraphRoundPreparerTest {
    private static final Instant AT = Instant.parse("2026-11-03T01:00:00Z");
    @TempDir Path temp;

    @Test void onlyAnAttemptWithKeptInputsAndNoSettledAnswerIsRecovered() {
        byte[] bytes = {1};
        // Kept its inputs, no result: the process stopped while composing.
        assertEquals(Optional.of(1L), GraphRoundPreparer.unsettled(row(1, null, bytes, null, null)));
        assertEquals(Optional.of(1L), GraphRoundPreparer.unsettled(row(1, null, bytes, "failed", "outcome_unknown")));
        // A recovery that met a temporary failure, or itself stopped, names the attempt it recovers.
        assertEquals(Optional.of(1L), GraphRoundPreparer.unsettled(row(2, 1L, bytes, "failed", "import_busy")));
        assertEquals(Optional.of(1L), GraphRoundPreparer.unsettled(row(2, 1L, bytes, null, null)));
        // Settled answers, and attempts that never composed.
        for (Preparation settled : List.of(row(1, null, bytes, "succeeded", "staged"), row(1, null, bytes, "failed", "correction_required"),
                row(1, null, bytes, "failed", "import_busy"), row(2, 1L, bytes, "failed", "active_conflict"),
                row(1, null, null, "succeeded", "nothing_to_prepare"), row(1, null, null, "failed", "first_publication_manual"))) {
            assertEquals(Optional.empty(), GraphRoundPreparer.unsettled(settled), settled.toString());
        }
    }

    @Test void startupRefusesWithoutRoundsWithAutoActivationOrWithoutTheRootOrRights() throws Exception {
        Path root = Files.createDirectory(temp.resolve("root"));
        Path rights = Files.writeString(temp.resolve("rights.json"), "{}");
        var rightsSet = new DocumentReadProperties(null, rights.toString(), null);
        assertRefused(env(root).withProperty("zoop.graph.round.enabled", "false"), rightsSet, "zoop.graph.round.enabled");
        assertRefused(env(root).withProperty("zoop.graph.auto-activation.enabled", "true"), rightsSet, "auto-activation");
        assertRefused(env(root).withProperty("zoop.graph.snapshot.source", "fixture"), rightsSet, "snapshot.source");
        assertRefused(env(temp.resolve("missing")), rightsSet, "artifact-root");
        assertRefused(env(root), new DocumentReadProperties(null, null, null), "ingestion-sources");
        // Every setting present: the refusal left is the missing round properties (rounds bound elsewhere).
        assertRefused(env(root), rightsSet, "zoop.graph.round.enabled");
    }

    private static void assertRefused(MockEnvironment env, DocumentReadProperties documentRead, String named) {
        var refused = assertThrows(GraphRoundConfigurationException.class, () -> new GraphRoundPrepareConfiguration().graphRoundPreparation(
                env, null, null, null, null, null, documentRead, null, null, null, null, new org.springframework.beans.factory.support.StaticListableBeanFactory()
                        .getBeanProvider(com.zoop.graph.round.GraphRoundProperties.class), null));
        assertTrue(refused.getMessage().contains(named), refused.getMessage());
    }

    private static MockEnvironment env(Path root) {
        return new MockEnvironment().withProperty("zoop.graph.round.enabled", "true").withProperty("zoop.graph.snapshot.source", "artifact")
                .withProperty("zoop.graph.snapshot.artifact-root", root.toString());
    }

    private static Preparation row(long id, Long recoveryOf, byte[] request, String status, String code) {
        return new Preparation(id, Optional.of("round-20261103T0905"), 7L, Optional.ofNullable(recoveryOf), AT, Optional.empty(),
                Optional.ofNullable(request), Optional.ofNullable(request), Optional.ofNullable(status), Optional.ofNullable(code),
                status == null ? Optional.empty() : Optional.of(AT));
    }
}
