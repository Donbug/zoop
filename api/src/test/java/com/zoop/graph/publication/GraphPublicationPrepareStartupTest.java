package com.zoop.graph.publication;

import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.context.support.GenericApplicationContext;
import org.springframework.mock.env.MockEnvironment;
import org.springframework.web.context.support.GenericWebApplicationContext;
import static org.junit.jupiter.api.Assertions.*;

/** The process rules the preparation runner checks before it builds anything (#55): one nonweb artifact-mode operator command. */
class GraphPublicationPrepareStartupTest {
    @Test void runsOnlyAsTheOneOperatorCommandOfANonwebArtifactProcess() {
        // The prepare runner names compose as its sibling and the compose runner names prepare.
        for (String sibling : List.of("graph-publication-compose", "graph-publication-prepare")) {
            assertDoesNotThrow(() -> GraphPublicationConfiguration.requireExclusiveOperator(context(false), sibling));
            assertThrows(IllegalArgumentException.class, () -> GraphPublicationConfiguration.requireExclusiveOperator(context(true), sibling));
            for (String conflict : List.of("zoop.graph.snapshot.source=fixture", "zoop.graph.snapshot.source=FIXTURE",
                    "zoop." + sibling + ".enabled=true", "zoop.graph-handoff-import.enabled=true", "zoop.document-import.enabled=true",
                    "zoop.document-analysis.enabled=true", "zoop.legacy-real-import.enabled=true", "zoop.document-bindings.enabled=true",
                    "zoop.disclosure-exclusion.enabled=true", "zoop.briefing.replay.import-enabled=true",
                    "zoop.graph-delivery.seal.enabled=true", "zoop.graph-delivery.install.enabled=true")) {
                String[] pair = conflict.split("=");
                var context = context(false);
                ((MockEnvironment) context.getEnvironment()).setProperty(pair[0], pair[1]);
                assertThrows(IllegalArgumentException.class,
                        () -> GraphPublicationConfiguration.requireExclusiveOperator(context, sibling), sibling + " " + conflict);
            }
        }
    }

    private static GenericApplicationContext context(boolean web) {
        var context = web ? new GenericWebApplicationContext() : new GenericApplicationContext();
        context.setEnvironment(new MockEnvironment());
        return context;
    }
}
