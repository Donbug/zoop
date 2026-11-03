package com.zoop.graph.publication;

import java.time.Clock;
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
 * The automatic preparation of the round path (#55 PR-P3): at the end of a scheduler pass, when an import came after the last
 * preparation, run the same {@link GraphPublicationPreparer} the operator command runs and keep every attempt in
 * {@link JdbcGraphPublicationPreparationRepository}. It never activates and never changes a round.
 *
 * <ul>
 * <li>Once per new import: an attempt answers the newest import ({@code trigger_sequence}, the import order of the newest staged
 *     snapshot that is not a composition, so a retried round's new version counts too). A settled answer is not repeated. A
 *     temporary failure ({@link #TEMPORARY}) is tried again after {@code retryAfter}, at most {@code maxAttempts} times for the
 *     same import; a conflict ({@link #CONFLICT}) at once.</li>
 * <li>An unknown outcome is recovered first, with the fixed inputs (11-02 AI reply): an attempt that kept its bytes but has no
 *     result (the process stopped while composing) or answered {@code outcome_unknown} is run again as an operator compose of
 *     exactly those bytes ({@link GraphPublicationPreparer#operatorCompose}), as a new row naming it. Only a settled recovery lets a
 *     new preparation run. A recovery that does not settle waits {@code retryAfter}; after {@code maxAttempts} of them it is
 *     logged as {@code recovery_required} and tried only every {@code retryAfter × maxAttempts}, so a person's operator compose of
 *     the same bytes (or a moved active pointer) settles it at the next try.</li>
 * <li>One at a time: the work holds the round import lock, so no round import and no other instance's preparation runs
 *     meanwhile; a busy lock waits for the next pass. It runs on the scheduler thread, so a long composition delays this
 *     instance's next pass (the slots are 30 minutes apart).</li>
 * <li>A failure outside the composer (the journal unavailable, say) pauses the step for {@code retryAfter} in this process.</li>
 * </ul>
 */
public final class GraphRoundPreparer implements RoundPreparation {
    private static final Logger log = LoggerFactory.getLogger(GraphRoundPreparer.class);
    /** Codes that say "try again later" rather than settle the attempt. */
    static final Set<String> TEMPORARY = Set.of("import_busy", "database_unavailable", "basis_unavailable", "source_authority_unavailable");
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
    private final int maxAttempts;
    private final Clock clock;
    private volatile Instant pausedUntil;

    public GraphRoundPreparer(GraphRoundRepository rounds, JdbcGraphPublicationPreparationRepository journal, GraphRoundImportLock lock,
            GraphPublicationPreparer preparer, GraphPublicationReader reader, JdbcGraphPublicationRepository publications,
            GraphPublicationComposer composer, Duration retryAfter, int maxAttempts, Clock clock) {
        this.rounds = rounds; this.journal = journal; this.lock = lock; this.preparer = preparer; this.reader = reader;
        this.publications = publications; this.composer = composer; this.retryAfter = retryAfter; this.maxAttempts = maxAttempts;
        this.clock = clock;
    }

    @Override
    public void afterPass(Instant passAt) {
        Instant now = clock.instant();
        Instant paused = pausedUntil;
        if (paused != null && now.isBefore(paused)) return;
        try {
            step(now);
        } catch (RuntimeException failure) {
            pausedUntil = now.plus(retryAfter);
            log.warn("graph publication preparation paused for {} after {}", retryAfter, failure.getClass().getSimpleName());
        }
    }

    private void step(Instant now) {
        Optional<Long> newest = publications.newestImport();
        if (newest.isEmpty()) return;
        long trigger = newest.get();
        if (!due(journal.latest(), trigger, now)) return; // nothing to do: no lock taken
        Optional<GraphRoundImportLock.Held> held = lock.tryAcquire();
        if (held.isEmpty()) return;
        try (GraphRoundImportLock.Held ignored = held.get()) {
            // Read again under the lock: an import another instance committed meanwhile is the one this attempt answers.
            newest = publications.newestImport();
            if (newest.isEmpty()) return;
            trigger = newest.get();
            Optional<Preparation> last = journal.latest();
            if (!due(last, trigger, now)) return;
            Optional<Long> unsettled = last.flatMap(GraphRoundPreparer::unsettled);
            if (unsettled.isPresent()) {
                if (!recover(unsettled.get())) return;
                last = journal.latest();
                if (last.isPresent() && answered(last.get(), trigger, clock.instant())) return;
            }
            prepare(rounds.newestImported().map(GraphRound::roundId).orElse(null), trigger);
        }
    }

    /** Whether there is work: an unknown outcome whose wait is over, or a newest import not yet answered. */
    private boolean due(Optional<Preparation> last, long trigger, Instant now) {
        if (last.isEmpty()) return true;
        Preparation row = last.get();
        Optional<Long> target = unsettled(row);
        if (target.isPresent()) {
            if (row.recoveryOf().isEmpty()) return true; // the first recovery runs at once
            Duration wait = journal.recoveries(target.get()) >= maxAttempts ? retryAfter.multipliedBy(maxAttempts) : retryAfter;
            return !row.completedAt().orElse(row.createdAt()).plus(wait).isAfter(now);
        }
        return !answered(row, trigger, now);
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
     * {@code retryAfter} until {@code maxAttempts} attempts answered the same import; a conflict is judged again at once.
     */
    private boolean answered(Preparation last, long trigger, Instant now) {
        if (last.triggerSequence() < trigger) return false;
        String code = last.code().orElse("");
        if (CONFLICT.contains(code)) return false;
        if (TEMPORARY.contains(code)) {
            if (journal.attempts(trigger) >= maxAttempts) return true;
            return last.completedAt().map(at -> at.plus(retryAfter).isAfter(now)).orElse(true);
        }
        return true;
    }

    /** Runs the unsettled attempt's fixed inputs again; true when it settled (a new preparation may follow). */
    private boolean recover(long target) {
        int before = journal.recoveries(target);
        if (before >= maxAttempts) {
            log.warn("graph publication preparation {}: recovery_required (outcome still unknown after {} recoveries; a person's operator "
                    + "compose of the kept bytes settles it)", target, before);
        }
        Preparation original = journal.find(target).orElseThrow();
        byte[] request = original.request().orElseThrow();
        byte[] decisions = original.decisions().orElseThrow();
        long id = journal.begin(original.roundId().orElse(null), original.triggerSequence(), target, original.activeVersionId().orElse(null),
                request, decisions, clock.instant());
        ObjectNode result;
        try {
            result = GraphPublicationPreparer.operatorCompose(reader, publications, composer, PublicationComposeRequest.parse(request), decisions);
        } catch (PublicationException invalid) {
            result = GraphPublicationComposer.failed(invalid.code());
        } catch (RuntimeException unexpected) {
            // Settle the row as the first attempt would (internal_error), so a failure that repeats does not pile up open rows.
            log.error("graph publication preparation {}: recovery failed unexpectedly: {}", id, unexpected.getClass().getName());
            result = GraphPublicationComposer.failed("internal_error");
        }
        journal.complete(id, result, clock.instant());
        String code = JdbcGraphPublicationPreparationRepository.code(result);
        log.info("graph publication preparation {}: recovery of {} answered {}", id, target, code);
        return !OUTCOME_UNKNOWN.equals(code) && !TEMPORARY.contains(code);
    }

    private void prepare(String roundId, long trigger) {
        long[] begun = {-1};
        ObjectNode result = preparer.run((active, request, decisions) -> begun[0] = journal.begin(roundId, trigger, null, active, request,
                decisions, clock.instant()));
        long id = begun[0] >= 0 ? begun[0] : journal.record(roundId, trigger, result, clock.instant());
        if (begun[0] >= 0) journal.complete(id, result, clock.instant());
        String code = JdbcGraphPublicationPreparationRepository.code(result);
        log.info("graph publication preparation {} after import {}: {}", id, trigger, code);
        if (TEMPORARY.contains(code) && journal.attempts(trigger) >= maxAttempts) {
            log.warn("graph publication preparation: {} after {} attempts for import {}; waiting for the next import", code, maxAttempts, trigger);
        }
    }
}
