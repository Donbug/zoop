package com.zoop.graph.round;

import java.time.DateTimeException;
import java.time.Duration;
import java.time.LocalTime;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.List;

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
 * @param busyRetryAfter    delay after the artifact store or the AI round was busy (another import, operator command or run held it)
 * @param maxAttemptsPerStage attempts at one stage before the round fails with {@code <stage>_timeout} (the analysis wait has its
 *                          own bound, {@code analysisWaitDeadline})
 * @param importSource      observation re-check: {@code cli} runs the local installed export; {@code http} uses the configured
 *                          observation-export client and the same importer verification
 * @param ingestionCli      {@code zoop-ai-ingest} executable (import-source cli)
 * @param ingestionStateDir the S2-1 ledger directory (import-source cli)
 * @param ingestionSources  the operator source registry (import-source cli)
 * @param interval          how often the scheduler thread looks at the rounds
 * @param lease             how long one instance owns a round row per claim; renewed by the same owner before every external call
 * @param zone              the slot calendar's zone (KST for the AI tick's 09:05..17:35)
 * @param firstSlotAt       the first regular slot of a day, {@code HH:mm} in {@code zone}
 * @param slotInterval      the distance between regular slots
 * @param slotCount         how many regular slots a day has (18 for 09:05..17:35 every 30 minutes)
 * @param freezeOnly        freeze-only slots, {@code HH:mm} each: no run, a carry-only freeze (team decision 8: {@code 18:05})
 * @param lookback          at start, slots this far back that have no row yet are opened (a restart does not drop a round)
 * @param maxOpenRounds     how many open rounds one pass moves (oldest first); the rest wait for the next pass
 * @param analysisWaitDeadline how long R4 waits for the analyze_plan job before the round fails with {@code analysis_timeout};
 *                          longer than {@code zoop.analysis.analyze-plan.attempt-deadline}
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
        @DefaultValue("") String ingestionSources,
        @DefaultValue("PT15S") Duration interval,
        @DefaultValue("PT2M") Duration lease,
        @DefaultValue("Asia/Seoul") String zone,
        @DefaultValue("09:05") String firstSlotAt,
        @DefaultValue("PT30M") Duration slotInterval,
        @DefaultValue("18") int slotCount,
        @DefaultValue("18:05") List<String> freezeOnly,
        @DefaultValue("PT30M") Duration lookback,
        @DefaultValue("3") int maxOpenRounds,
        @DefaultValue("PT2H") Duration analysisWaitDeadline) {

    public GraphRoundProperties {
        bounded("wait-retry-after", waitRetryAfter, Duration.ofSeconds(1), Duration.ofHours(1));
        bounded("busy-retry-after", busyRetryAfter, Duration.ofSeconds(1), Duration.ofHours(1));
        bounded("interval", interval, Duration.ofSeconds(1), Duration.ofMinutes(10));
        bounded("lease", lease, Duration.ofSeconds(10), Duration.ofHours(1));
        bounded("slot-interval", slotInterval, Duration.ofMinutes(1), Duration.ofHours(24));
        bounded("lookback", lookback, Duration.ZERO, Duration.ofHours(24));
        bounded("analysis-wait-deadline", analysisWaitDeadline, Duration.ofMinutes(1), Duration.ofHours(24));
        if (maxAttemptsPerStage < 1 || maxAttemptsPerStage > 1000) {
            throw new GraphRoundConfigurationException("max-attempts-per-stage", "must be between 1 and 1000");
        }
        if (slotCount < 1 || slotCount > 288) {
            throw new GraphRoundConfigurationException("slot-count", "must be between 1 and 288");
        }
        if (maxOpenRounds < 1 || maxOpenRounds > 100) {
            throw new GraphRoundConfigurationException("max-open-rounds", "must be between 1 and 100");
        }
        if (operator == null || !com.zoop.graph.importer.GraphHandoffRequestParser.OPERATOR.matcher(operator).matches()) {
            throw new GraphRoundConfigurationException("operator", "must be an operator name of the import request alphabet");
        }
        slotZone(zone);
        LocalTime first = time("first-slot-at", firstSlotAt);
        if (first.toSecondOfDay() + slotInterval.toSeconds() * (slotCount - 1) >= 24 * 3600) {
            throw new GraphRoundConfigurationException("slot-count", "regular slots must stay within one calendar day");
        }
        List<LocalTime> regular = new ArrayList<>();
        for (int k = 0; k < slotCount; k++) regular.add(first.plus(slotInterval.multipliedBy(k)));
        freezeOnly = freezeOnly == null ? List.of() : List.copyOf(freezeOnly);
        List<LocalTime> freezes = new ArrayList<>();
        for (String value : freezeOnly) {
            LocalTime time = time("freeze-only", value);
            if (regular.contains(time) || freezes.contains(time)) {
                throw new GraphRoundConfigurationException("freeze-only", "must not repeat a regular slot or another freeze-only slot");
            }
            freezes.add(time);
        }
    }

    public ZoneId slotZone() {
        return slotZone(zone);
    }

    public LocalTime firstSlot() {
        return time("first-slot-at", firstSlotAt);
    }

    public List<LocalTime> freezeOnlySlots() {
        return freezeOnly.stream().map(value -> time("freeze-only", value)).toList();
    }

    private static ZoneId slotZone(String value) {
        if (value == null || value.isBlank()) throw new GraphRoundConfigurationException("zone", "is required");
        try {
            return ZoneId.of(value.strip());
        } catch (DateTimeException error) {
            throw new GraphRoundConfigurationException("zone", "must be a known zone id");
        }
    }

    private static LocalTime time(String setting, String value) {
        if (value == null || !value.strip().matches("[0-9]{2}:[0-9]{2}")) {
            throw new GraphRoundConfigurationException(setting, "must be HH:mm");
        }
        try {
            return LocalTime.parse(value.strip());
        } catch (DateTimeException error) {
            throw new GraphRoundConfigurationException(setting, "must be HH:mm");
        }
    }

    private static void bounded(String name, Duration value, Duration minimum, Duration maximum) {
        if (value == null || value.compareTo(minimum) < 0 || value.compareTo(maximum) > 0) {
            throw new GraphRoundConfigurationException(name, "is outside its bounds");
        }
    }
}
