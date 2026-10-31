package com.zoop.graph.round;

import java.time.Duration;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

/**
 * {@code zoop.graph.round.*}: the periodic public-graph round inside the web application (#55). Off by default; nothing here is
 * read unless {@code enabled} is true, and then every value is checked at startup.
 *
 * @param operator          the importer's operator for round imports ({@code graph_versions.created_by = "operator:<operator>"}),
 *                          in the operator request's own alphabet; the round's {@code started_by} is {@code system:scheduler}
 *                          regardless
 * @param waitRetryAfter    delay before a waiting stage is tried again (an unavailable source, a job not finished yet)
 * @param busyRetryAfter    delay after the artifact store was busy (another import or operator command held it)
 * @param maxAttemptsPerStage attempts at one stage before the round fails with {@code <stage>_timeout}
 * @param importSource      the observation re-check of the import: {@code cli} runs the installed {@code zoop-ai-ingest export}
 *                          (local, single-instance operation only), {@code http} is reserved for the AI side's observation
 *                          export route (#387 ③) and is refused until it exists
 * @param ingestionCli      {@code zoop-ai-ingest} executable (import-source cli)
 * @param ingestionStateDir the S2-1 ledger directory (import-source cli)
 * @param ingestionSources  the operator source registry (import-source cli)
 */
@ConfigurationProperties("zoop.graph.round")
public record GraphRoundProperties(
        @DefaultValue("false") boolean enabled,
        @DefaultValue("scheduler") String operator,
        @DefaultValue("PT1M") Duration waitRetryAfter,
        @DefaultValue("PT5M") Duration busyRetryAfter,
        @DefaultValue("20") int maxAttemptsPerStage,
        @DefaultValue("cli") String importSource,
        @DefaultValue("") String ingestionCli,
        @DefaultValue("") String ingestionStateDir,
        @DefaultValue("") String ingestionSources) {

    public GraphRoundProperties {
        bounded("wait-retry-after", waitRetryAfter, Duration.ofSeconds(1), Duration.ofHours(1));
        bounded("busy-retry-after", busyRetryAfter, Duration.ofSeconds(1), Duration.ofHours(1));
        if (maxAttemptsPerStage < 1 || maxAttemptsPerStage > 1000) {
            throw new GraphRoundConfigurationException("max-attempts-per-stage", "must be between 1 and 1000");
        }
        if (operator == null || !com.zoop.graph.importer.GraphHandoffRequestParser.OPERATOR.matcher(operator).matches()) {
            throw new GraphRoundConfigurationException("operator", "must be an operator name of the import request alphabet");
        }
    }

    private static void bounded(String name, Duration value, Duration minimum, Duration maximum) {
        if (value == null || value.compareTo(minimum) < 0 || value.compareTo(maximum) > 0) {
            throw new GraphRoundConfigurationException(name, "is outside its bounds");
        }
    }
}
