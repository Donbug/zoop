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
 * <li>{@code staged} / {@code unchanged} → {@code imported} with the version id. Activation stays the auto-activation
 *     scheduler's.</li>
 * <li>an older slot than the newest round already imported → {@code skipped} ({@code skipped_superseded}): the auto-activation
 *     picks by commit order, so a late import of an older round must never become public after a newer one. Under the cumulative
 *     bundle contract the newer round already holds the older one's content. The check and the import happen under one
 *     database-wide {@link GraphRoundImportLock}, so no other instance can import in between; when the lock is held elsewhere
 *     the round waits like for a busy store.</li>
 * <li>a transient failure (store busy, source unavailable, database unavailable) → the row waits and is tried again later; past
 *     {@code max-attempts-per-stage} the round fails with {@code import_timeout}.</li>
 * <li>every other failure → {@code failed(import:<code>)}; the round keeps its id and can be retried.</li>
 * </ul>
 * Runs on the caller's thread (the round scheduler's own, never a request thread) and takes no lock itself: the importer holds
 * the artifact store lock for the run and answers {@code import_busy} when an operator command holds it.
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
     * Imports the round's handoff and records the outcome; the round must be at {@code handoff_ready} with its handoff id and both
     * digests. Returns the row as it is afterwards.
     */
    public GraphRound importRound(String roundId) {
        GraphRound round = rounds.find(roundId).orElseThrow(() -> new IllegalArgumentException("unknown round"));
        if (round.stage() != GraphRoundStage.HANDOFF_READY) {
            throw new IllegalStateException("round is not at handoff_ready");
        }
        String handoffId = round.handoffId().orElseThrow(() -> new IllegalStateException("round has no handoff"));
        String manifestDigest = round.manifestDigest().orElseThrow(() -> new IllegalStateException("round has no manifest digest"));
        String bundleDigest = round.bundleDigest().orElseThrow(() -> new IllegalStateException("round has no bundle digest"));

        Optional<GraphRoundImportLock.Held> held = lock.tryAcquire();
        if (held.isEmpty()) {
            return wait(round, IMPORT_LOCKED, nodes.objectNode(), busyRetryAfter);
        }
        try (GraphRoundImportLock.Held ignored = held.get()) {
            return imported(round, handoffId, manifestDigest, bundleDigest);
        }
    }

    private GraphRound imported(GraphRound round, String handoffId, String manifestDigest, String bundleDigest) {
        String roundId = round.roundId();
        Optional<GraphRound> newest = rounds.newestImported();
        if (newest.isPresent() && newest.get().slotAt().isAfter(round.slotAt())) {
            log.info("graph round {} skipped: round {} was imported already", roundId, newest.get().roundId());
            ObjectNode detail = nodes.objectNode();
            detail.put("supersededBy", newest.get().roundId());
            return rounds.advance(roundId, GraphRoundPatch.advanceTo(GraphRoundStage.SKIPPED), Outcome.SKIPPED,
                    SKIPPED_SUPERSEDED, null, detail, clock.instant());
        }

        // run() never throws: an unexpected failure comes back as internal_error.
        GraphHandoffResult result = importer.run(new GraphHandoffRequest(handoffId, manifestDigest, bundleDigest, operator));
        Instant now = clock.instant();
        if (result.succeeded()) {
            GraphHandoffResult.Staged staged = result.staged();
            ObjectNode detail = nodes.objectNode();
            detail.put("versionId", staged.versionId());
            detail.put("outcome", staged.outcome().wire());
            detail.put("manifestDigest", staged.manifestDigest());
            detail.put("bundleDigest", staged.bundleDigest());
            log.info("graph round {} imported: {} {}", roundId, staged.outcome().wire(), staged.versionId());
            return rounds.advance(roundId, GraphRoundPatch.advanceTo(GraphRoundStage.IMPORTED).graphVersion(staged.versionId()),
                    Outcome.ADVANCED, staged.outcome().wire(), null, detail, now);
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
        return rounds.advance(roundId, GraphRoundPatch.fail(code), Outcome.FAILED, code, null, detail, now);
    }

    /** A transient failure: the row waits for {@code retryAfter}, or fails with {@code import_timeout} at the attempt bound. */
    private GraphRound wait(GraphRound round, String code, ObjectNode detail, Duration retryAfter) {
        Instant now = clock.instant();
        if (round.attempts() + 1 >= maxAttempts) {
            log.warn("graph round {} import gave up after {} attempts: {}", round.roundId(), round.attempts() + 1, code);
            return rounds.advance(round.roundId(), GraphRoundPatch.fail(IMPORT_TIMEOUT), Outcome.FAILED, code, null, detail, now);
        }
        Instant next = now.plus(retryAfter);
        log.info("graph round {} import waits until {}: {}", round.roundId(), next, code);
        return rounds.advance(round.roundId(), GraphRoundPatch.waitAt(GraphRoundStage.HANDOFF_READY, next), Outcome.WAITING,
                code, null, detail, now);
    }
}
