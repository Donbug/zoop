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
        assertDoesNotThrow(() -> GraphPublicationConfiguration.requireExclusiveOperator(context(false), "graph-publication-compose"));
        assertThrows(IllegalArgumentException.class,
                () -> GraphPublicationConfiguration.requireExclusiveOperator(context(true), "graph-publication-compose"));
        for (String conflict : List.of("zoop.graph.snapshot.source=fixture", "zoop.graph-publication-compose.enabled=true",
                "zoop.graph-handoff-import.enabled=true", "zoop.document-import.enabled=true", "zoop.disclosure-exclusion.enabled=true",
                "zoop.graph-delivery.seal.enabled=true", "zoop.graph-delivery.install.enabled=true")) {
            String[] pair = conflict.split("=");
            var context = context(false);
            ((MockEnvironment) context.getEnvironment()).setProperty(pair[0], pair[1]);
            assertThrows(IllegalArgumentException.class,
                    () -> GraphPublicationConfiguration.requireExclusiveOperator(context, "graph-publication-compose"), conflict);
        }
    }

    private static GenericApplicationContext context(boolean web) {
        var context = web ? new GenericWebApplicationContext() : new GenericApplicationContext();
        context.setEnvironment(new MockEnvironment());
        return context;
    }
}
