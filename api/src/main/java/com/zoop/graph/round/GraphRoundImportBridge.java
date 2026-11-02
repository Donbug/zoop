package com.zoop.graph.round;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.Optional;
import java.util.Set;

import com.zoop.graph.importer.GraphHandoffException;
import com.zoop.graph.importer.GraphHandoffFailure;
import com.zoop.graph.importer.GraphHandoffImporter;
import com.zoop.graph.importer.GraphHandoffRequest;
import com.zoop.graph.importer.GraphHandoffResult;
import com.zoop.graph.round.GraphRoundEvent.Outcome;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import tools.jackson.databind.node.JsonNodeFactory;
import tools.jackson.databind.node.ObjectNode;

/**
 * R7 of a round: the handoff the AI side froze for it is staged as an inactive graph version by the same
 * {@link GraphHandoffImporter} the operator command runs, inside the web application (decision D-R1, 2026-10-29). The importer's
 * meaning is unchanged (one bundle = one inactive version; the same pins stage once and answer {@code unchanged} afterwards);
 * this class only takes the round's pins, calls it, and records the outcome on the round row and its timeline:
 * <ul>
 * <li>{@code staged} / {@code unchanged} → {@code imported} with the version id. The round row is linked to the version
 *     <em>inside the import transaction</em> ({@link GraphRoundRepository#link}), so the version and the round's claim on it
 *     commit together; the stage change to {@code imported} follows in its own transaction. A crash between the two leaves an
 *     open row with its version linked: the next attempt runs the same pins again, gets {@code unchanged}, and completes the
 *     stage change, whatever was imported meanwhile (its own import is committed; it is not a candidate for a skip). A linked
 *     version that is not the one these pins produce (the round was given another handoff without a retry clearing the link)
 *     is {@code failed(import:version_conflict)} before anything is read. Activation stays the auto-activation
 *     scheduler's.</li>
 * <li>an older slot than the newest round whose import committed, with no committed import of its own → {@code skipped}
 *     ({@code skipped_superseded}): the
 *     auto-activation picks by commit order, so a late import of an older round must never become public after a newer one.
 *     The guard reads {@link GraphRoundRepository#newestImported()} (stage {@code imported}, or a version committed in the
 *     import transaction: {@code versionCommittedAt}, which no retry clears), never the stage alone. A retry that keeps the
 *     pins keeps the link too, so such a round completes as {@code unchanged}; a retry that froze again dropped the link, and
 *     its new handoff is skipped like any older slot's (the version its earlier import made stays registered; the skip's
 *     detail carries {@code versionCommittedAt} then). The check and the import happen under one database-wide
 *     {@link GraphRoundImportLock}, so no other instance can import in between; when the lock is held elsewhere the round
 *     waits like for a busy store. What the skipped round's bundle held is covered only under a cumulative bundle contract
 *     (AI side, #407 clause 2, not fixed yet): until then a skip is a round whose content was not imported.</li>
 * <li>a transient failure (store busy, source unavailable, database unavailable) → the row waits and is tried again later; past
 *     {@code max-attempts-per-stage} the round fails with {@code import_timeout}.</li>
 * <li>every other failure → {@code failed(import:<code>)}; the round keeps its id and can be retried.</li>
 * </ul>
 * Fencing: the caller passes the row as it claimed it (its lease token). Every write here, the link included, is fenced on
 * that token and the {@code handoff_ready} stage; when the lease was taken over meanwhile, nothing is written (an import in
 * flight is rolled back) and the row is returned as the new holder left it.
 *
 * <p>Runs on the caller's thread (the round scheduler's own, never a request thread) and takes no lock itself: the importer
 * holds the artifact store lock for the run and answers {@code import_busy} when an operator command holds it. The lease must
 * cover the import (minutes) or be renewed by its holder meanwhile; a renewal by the same holder keeps the token.
 */
public final class GraphRoundImportBridge {
    private static final Logger log = LoggerFactory.getLogger(GraphRoundImportBridge.class);
    static final String SKIPPED_SUPERSEDED = "skipped_superseded";
    static final String IMPORT_TIMEOUT = "import_timeout";
    static final String IMPORT_LOCKED = "import:round_import_busy";
    private static final Set<GraphHandoffFailure> WAIT = Set.of(GraphHandoffFailure.HANDOFF_EXPORT_UNAVAILABLE,
            GraphHandoffFailure.INGESTION_EXPORT_UNAVAILABLE, GraphHandoffFailure.DATABASE_UNAVAILABLE,
            GraphHandoffFailure.ARTIFACT_STORE_UNAVAILABLE);

    private final GraphHandoffImporter importer;
    private final GraphRoundRepository rounds;
    private final GraphRoundImportLock lock;
    private final String operator;
    private final Duration waitRetryAfter;
    private final Duration busyRetryAfter;
    private final int maxAttempts;
    private final Clock clock;
    private final JsonNodeFactory nodes = JsonNodeFactory.instance;

    public GraphRoundImportBridge(GraphHandoffImporter importer, GraphRoundRepository rounds, GraphRoundImportLock lock,
            GraphRoundProperties properties, Clock clock) {
        this(importer, rounds, lock, properties.operator(), properties.waitRetryAfter(), properties.busyRetryAfter(),
                properties.maxAttemptsPerStage(), clock);
    }

    public GraphRoundImportBridge(GraphHandoffImporter importer, GraphRoundRepository rounds, GraphRoundImportLock lock,
            String operator, Duration waitRetryAfter, Duration busyRetryAfter, int maxAttempts, Clock clock) {
        this.importer = importer;
        this.rounds = rounds;
        this.lock = lock;
        this.operator = operator;
        this.waitRetryAfter = waitRetryAfter;
        this.busyRetryAfter = busyRetryAfter;
        this.maxAttempts = maxAttempts;
        this.clock = clock;
    }

    /**
     * Imports the round's handoff and records the outcome. {@code claimed} is the row as the caller took it with
     * {@link GraphRoundRepository#claim}: at {@code handoff_ready} with its handoff id and both digests, and with a lease.
     * Returns the row as it is afterwards; when the lease was taken over meanwhile, the row as the new holder left it.
     */
    public GraphRound importRound(GraphRound claimed) {
        if (claimed.lease().isEmpty()) {
            throw new IllegalArgumentException("the round must be claimed first");
        }
        if (claimed.stage() != GraphRoundStage.HANDOFF_READY) {
            throw new IllegalStateException("round is not at handoff_ready");
        }
        String handoffId = claimed.handoffId().orElseThrow(() -> new IllegalStateException("round has no handoff"));
        String manifestDigest = claimed.manifestDigest().orElseThrow(() -> new IllegalStateException("round has no manifest digest"));
        String bundleDigest = claimed.bundleDigest().orElseThrow(() -> new IllegalStateException("round has no bundle digest"));

        Optional<GraphRoundImportLock.Held> held = lock.tryAcquire();
        if (held.isEmpty()) {
            return wait(claimed, IMPORT_LOCKED, nodes.objectNode(), busyRetryAfter);
        }
        try (GraphRoundImportLock.Held ignored = held.get()) {
            return imported(claimed, handoffId, manifestDigest, bundleDigest);
        }
    }

    private GraphRound imported(GraphRound round, String handoffId, String manifestDigest, String bundleDigest) {
        String roundId = round.roundId();
        String versionId = GraphHandoffImporter.versionId(handoffId);
        Optional<String> linked = round.graphVersionId();
        if (linked.isPresent() && !linked.get().equals(versionId)) {
            // The row guard refuses a change between two versions; a retry (retryAt) is the way to forget the old link.
            String code = "import:" + GraphHandoffFailure.VERSION_CONFLICT.code();
            log.warn("graph round {} import failed: {} (another version is linked)", roundId, code);
            ObjectNode detail = nodes.objectNode();
            detail.put("failure", GraphHandoffFailure.VERSION_CONFLICT.code());
            detail.put("linkedVersionId", linked.get());
            detail.put("versionId", versionId);
            return record(round, GraphRoundPatch.fail(code), Outcome.FAILED, code, detail, clock.instant());
        }
        Optional<GraphRound> newest = linked.isPresent() ? Optional.empty() : rounds.newestImported();
        if (newest.isPresent() && newest.get().slotAt().isAfter(round.slotAt())) {
            log.info("graph round {} skipped: round {} was imported already", roundId, newest.get().roundId());
            ObjectNode detail = nodes.objectNode();
            detail.put("supersededBy", newest.get().roundId());
            round.versionCommittedAt().ifPresent(at -> detail.put("versionCommittedAt", at.toString()));
            return record(round, GraphRoundPatch.advanceTo(GraphRoundStage.SKIPPED), Outcome.SKIPPED, SKIPPED_SUPERSEDED, detail,
                    clock.instant());
        }

        // run() never throws for the import's own failures (an unexpected one comes back as internal_error); the recorder's
        // refusal is the one exception, after the rollback.
        GraphHandoffResult result;
        try {
            result = importer.run(new GraphHandoffRequest(handoffId, manifestDigest, bundleDigest, operator), staged -> {
                if (!rounds.link(round, staged.versionId(), clock.instant())) {
                    throw new GraphHandoffImporter.RecordRefused();
                }
            });
        } catch (GraphHandoffImporter.RecordRefused refused) {
            return fenced(round);
        }
        Instant now = clock.instant();
        if (result.succeeded()) {
            GraphHandoffResult.Staged staged = result.staged();
            ObjectNode detail = nodes.objectNode();
            detail.put("versionId", staged.versionId());
            detail.put("outcome", staged.outcome().wire());
            detail.put("manifestDigest", staged.manifestDigest());
            detail.put("bundleDigest", staged.bundleDigest());
            log.info("graph round {} imported: {} {}", roundId, staged.outcome().wire(), staged.versionId());
            return record(round, GraphRoundPatch.advanceTo(GraphRoundStage.IMPORTED).graphVersion(staged.versionId()),
                    Outcome.ADVANCED, staged.outcome().wire(), detail, now);
        }

        GraphHandoffException failure = result.failure();
        String code = "import:" + failure.failure().code();
        ObjectNode detail = nodes.objectNode();
        detail.put("failure", failure.failure().code());
        if (failure.cliCode() != null) detail.put("code", failure.cliCode());
        if (failure.observation() >= 0) detail.put("observation", failure.observation());
        boolean busy = failure.failure() == GraphHandoffFailure.IMPORT_BUSY;
        if (busy || WAIT.contains(failure.failure())) {
            return wait(round, code, detail, busy ? busyRetryAfter : waitRetryAfter);
        }
        log.warn("graph round {} import failed: {}", roundId, code);
        return record(round, GraphRoundPatch.fail(code), Outcome.FAILED, code, detail, now);
    }

    /** A transient failure: the row waits for {@code retryAfter}, or fails with {@code import_timeout} at the attempt bound. */
    private GraphRound wait(GraphRound round, String code, ObjectNode detail, Duration retryAfter) {
        Instant now = clock.instant();
        if (round.attempts() + 1 >= maxAttempts) {
            log.warn("graph round {} import gave up after {} attempts: {}", round.roundId(), round.attempts() + 1, code);
            return record(round, GraphRoundPatch.fail(IMPORT_TIMEOUT), Outcome.FAILED, code, detail, now);
        }
        Instant next = now.plus(retryAfter);
        log.info("graph round {} import waits until {}: {}", round.roundId(), next, code);
        return record(round, GraphRoundPatch.waitAt(GraphRoundStage.HANDOFF_READY, next), Outcome.WAITING, code, detail, now);
    }

    /** Every outcome goes through the same fenced write. */
    private GraphRound record(GraphRound round, GraphRoundPatch patch, Outcome outcome, String code, ObjectNode detail,
            Instant at) {
        return rounds.advance(round, patch, outcome, code, null, detail, at).orElseGet(() -> fenced(round));
    }

    /** The lease was taken over (or the row moved on) while this attempt ran: nothing of it is recorded. */
    private GraphRound fenced(GraphRound round) {
        log.warn("graph round {} outcome not recorded: the lease was taken over or the row moved on", round.roundId());
        return rounds.find(round.roundId()).orElseThrow(() -> new IllegalStateException("round not found: " + round.roundId()));
    }
}
