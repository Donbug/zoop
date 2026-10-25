package com.zoop.admin.graph;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.graph.version.GraphVersionRecord;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.autoconfigure.condition.ConditionalOnWebApplication;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * The app's one public-round scheduler (FS059, AI owner answer 2026-10-25): after an operator import stages a version, the web
 * application makes the newest one public once it passes the same checks as an admin activation. The import itself stays the
 * operator command, and so do the AI side's commands; this never runs one.
 * <ul>
 * <li>Off by default ({@code zoop.graph.auto-activation.enabled}); a restart changes it. Only versions imported after this
 *     scheduler started count, so turning it back on never publishes what piled up while it was off.</li>
 * <li>Web application only: the import and exclusion commands start the same jar without a web server and must never run it.</li>
 * <li>A refused version (rights, evidence, exclusions) keeps the old pointer and is retried after {@code retry-after}; an
 *     unavailable source is retried on the next run. Every decision is taken again under the publication lock.</li>
 * </ul>
 */
@Component
@ConditionalOnWebApplication
@ConditionalOnProperty(name = "zoop.graph.auto-activation.enabled", havingValue = "true")
@EnableScheduling
public class GraphAutoActivationScheduler {
    private static final Logger log = LoggerFactory.getLogger(GraphAutoActivationScheduler.class);

    private final AdminGraphVersionService service;
    private final Clock clock;
    private final Duration retryAfter;
    private final Instant since;
    /** Version id → earliest next attempt after a refusal. Lost on restart, which only means one earlier retry. */
    private final Map<String, Instant> refusedUntil = new HashMap<>();

    public GraphAutoActivationScheduler(AdminGraphVersionService service, Clock clock,
            @Value("${zoop.graph.auto-activation.retry-after:PT5M}") Duration retryAfter) {
        this.service = service;
        this.clock = clock;
        this.retryAfter = retryAfter;
        this.since = clock.instant();
    }

    @Scheduled(fixedDelayString = "${zoop.graph.auto-activation.interval:PT15S}",
            initialDelayString = "${zoop.graph.auto-activation.interval:PT15S}")
    public void run() {
        try {
            runOnce();
        } catch (RuntimeException unexpected) {
            log.warn("graph auto-activation run failed; the pointer is unchanged", unexpected);
        }
    }

    void runOnce() {
        GraphVersionRecord candidate = service.importedCandidate(since).orElse(null);
        if (candidate == null) return;
        Instant now = clock.instant();
        Instant until = refusedUntil.get(candidate.id());
        if (until != null && now.isBefore(until)) return;
        String requestId = "auto-activation-" + UUID.randomUUID();
        try {
            service.activateImported(candidate, since, requestId).ifPresentOrElse(
                    activation -> log.info("Graph auto-activation (graphVersion={}, previous={}, requestId={})",
                            candidate.id(), activation.previousVersionId(), requestId),
                    () -> log.info("Graph auto-activation skipped: another activation or a newer import won (graphVersion={}, "
                            + "requestId={})", candidate.id(), requestId));
            refusedUntil.clear();
        } catch (CustomException refused) {
            if (refused.getErrorCode() == ErrorCode.SOURCE_UNAVAILABLE) {
                log.warn("Graph auto-activation deferred: a source is unavailable (graphVersion={}, requestId={})",
                        candidate.id(), requestId);
                return;
            }
            refusedUntil.put(candidate.id(), now.plus(retryAfter));
            log.warn("Graph auto-activation refused (graphVersion={}, code={}, retryAt={}, requestId={})", candidate.id(),
                    refused.getErrorCode(), now.plus(retryAfter), requestId);
        }
    }
}
