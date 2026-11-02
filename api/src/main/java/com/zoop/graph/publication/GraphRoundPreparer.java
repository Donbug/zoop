package com.zoop.graph.publication;

import java.time.Duration;
import java.time.Instant;
import java.util.Optional;
import java.util.Set;
import com.zoop.graph.publication.JdbcGraphPublicationPreparationRepository.Preparation;
import com.zoop.graph.round.GraphRound;
import com.zoop.graph.round.GraphRoundImportLock;
import com.zoop.graph.round.GraphRoundRepository;
import com.zoop.graph.round.RoundPreparation;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import tools.jackson.databind.node.ObjectNode;

/**
 * The automatic preparation of the round path (#55 PR-P3): at the end of a scheduler pass, when a round import committed after the
 * last preparation, run the same {@link GraphPublicationPreparer} the operator command runs and keep every attempt in
 * {@link JdbcGraphPublicationPreparationRepository}. It never activates and never changes a round.
 *
 * <ul>
 * <li>Once per new import: an attempt answers the newest import commit ({@code trigger_committed_at}); a settled answer to it is
 *     not repeated. A temporary failure ({@link #TEMPORARY}) is tried again after {@code retryAfter}; a conflict ({@link #CONFLICT})
 *     at once.</li>
 * <li>An unknown outcome is recovered first, with the fixed inputs (11-02 AI reply): an attempt that kept its bytes but has no
 *     result (the process stopped while composing) or answered {@code outcome_unknown} is run again as an operator compose of
 *     exactly those bytes ({@link GraphPublicationPreparer#operatorCompose}), as a new row naming it. Only a settled recovery lets a
 *     new preparation run; after {@code maxRecoveries} unsettled ones, preparation stops for a person.</li>
 * <li>One at a time: the whole step holds the round import lock, so no round import and no other instance's preparation runs
 *     meanwhile; a busy lock waits for the next pass.</li>
 * </ul>
 */
public final class GraphRoundPreparer implements RoundPreparation {
    private static final Logger log = LoggerFactory.getLogger(GraphRoundPreparer.class);
    /** Codes that say "try again later" rather than settle the attempt. */
    static final Set<String> TEMPORARY = Set.of("import_busy", "database_unavailable", "basis_unavailable", "source_authority_unavailable",
            "artifact_store_unavailable");
    /** Codes that end the attempt because the state it read moved; a new preparation judges the moved state. */
    static final Set<String> CONFLICT = Set.of("active_conflict", "revision_conflict");
    static final String OUTCOME_UNKNOWN = "outcome_unknown";

    private final GraphRoundRepository rounds;
    private final JdbcGraphPublicationPreparationRepository journal;
    private final GraphRoundImportLock lock;
    private final GraphPublicationPreparer preparer;
    private final GraphPublicationReader reader;
    private final JdbcGraphPublicationRepository publications;
    private final GraphPublicationComposer composer;
    private final Duration retryAfter;
    private final int maxRecoveries;

    public GraphRoundPreparer(GraphRoundRepository rounds, JdbcGraphPublicationPreparationRepository journal, GraphRoundImportLock lock,
            GraphPublicationPreparer preparer, GraphPublicationReader reader, JdbcGraphPublicationRepository publications,
            GraphPublicationComposer composer, Duration retryAfter, int maxRecoveries) {
        this.rounds = rounds; this.journal = journal; this.lock = lock; this.preparer = preparer; this.reader = reader;
        this.publications = publications; this.composer = composer; this.retryAfter = retryAfter; this.maxRecoveries = maxRecoveries;
    }

    @Override
    public void afterPass(Instant now) {
        Optional<GraphRound> newest = rounds.newestImported();
        if (newest.isEmpty() || newest.get().versionCommittedAt().isEmpty()) return;
        String roundId = newest.get().roundId();
        Instant trigger = newest.get().versionCommittedAt().get();
        Optional<GraphRoundImportLock.Held> held = lock.tryAcquire();
        if (held.isEmpty()) return;
        try (GraphRoundImportLock.Held ignored = held.get()) {
            Optional<Preparation> last = journal.latest();
            Optional<Long> unsettled = last.flatMap(GraphRoundPreparer::unsettled);
            if (unsettled.isPresent()) {
                if (!recover(unsettled.get(), now)) return;
                last = journal.latest();
            }
            if (last.isPresent() && answered(last.get(), trigger, now)) return;
            prepare(roundId, trigger, now);
        }
    }

    /** The attempt whose outcome is still unknown, when the newest row leaves one. */
    static Optional<Long> unsettled(Preparation last) {
        long target = last.recoveryOf().orElse(last.id());
        if (last.composedWithoutResult()) return Optional.of(target);
        if (last.request().isEmpty()) return Optional.empty();
        String code = last.code().orElse("");
        if (OUTCOME_UNKNOWN.equals(code)) return Optional.of(target);
        if (last.recoveryOf().isPresent() && TEMPORARY.contains(code)) return Optional.of(target);
        return Optional.empty();
    }

    /**
     * True when {@code last} already answers the newest import: it came after it and settled. A temporary failure is due again after
     * {@code retryAfter}; a conflict (the active pointer or the rules moved while it ran) is judged again at once by a new preparation.
     */
    private boolean answered(Preparation last, Instant trigger, Instant now) {
        if (last.triggerCommittedAt().isBefore(trigger)) return false;
        String code = last.code().orElse("");
        if (CONFLICT.contains(code)) return false;
        if (TEMPORARY.contains(code)) return last.completedAt().map(at -> at.plus(retryAfter).isAfter(now)).orElse(true);
        return true;
    }

    /** Runs the unsettled attempt's fixed inputs again; true when it settled (a new preparation may follow). */
    private boolean recover(long target, Instant now) {
        if (journal.recoveries(target) >= maxRecoveries) {
            log.warn("graph publication preparation {}: recovery_required (outcome still unknown after {} recoveries)", target, maxRecoveries);
            return false;
        }
        Preparation original = journal.find(target).orElseThrow();
        byte[] request = original.request().orElseThrow();
        byte[] decisions = original.decisions().orElseThrow();
        long id = journal.begin(original.roundId().orElse(null), original.triggerCommittedAt(), target,
                original.activeVersionId().orElse(null), request, decisions, now);
        ObjectNode result;
        try {
            result = GraphPublicationPreparer.operatorCompose(reader, publications, composer, PublicationComposeRequest.parse(request), decisions);
        } catch (PublicationException invalid) {
            result = GraphPublicationComposer.failed(invalid.code());
        }
        journal.complete(id, result, now);
        String code = JdbcGraphPublicationPreparationRepository.code(result);
        log.info("graph publication preparation {}: recovery of {} answered {}", id, target, code);
        return !OUTCOME_UNKNOWN.equals(code) && !TEMPORARY.contains(code);
    }

    private void prepare(String roundId, Instant trigger, Instant now) {
        long[] begun = {-1};
        ObjectNode result = preparer.run((active, request, decisions) -> begun[0] = journal.begin(roundId, trigger, null, active, request,
                decisions, now));
        long id = begun[0] >= 0 ? begun[0] : journal.record(roundId, trigger, result, now);
        if (begun[0] >= 0) journal.complete(id, result, now);
        log.info("graph publication preparation {} after round {}: {}", id, roundId, JdbcGraphPublicationPreparationRepository.code(result));
    }
}
