package com.zoop.graph.round;

import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Optional;

import com.zoop.graph.round.GraphRoundEvent.Outcome;
import tools.jackson.databind.JsonNode;

/**
 * The round rows and their timelines. Short transactions only: a caller never holds a row across an external call; it takes a
 * lease, calls, then records the outcome in one {@link #advance} transaction.
 *
 * <p>Fencing: {@link #claim} issues a token with every new lease. {@link #advance} and {@link #link} write only while the row
 * is still at the stage the caller saw under that token; otherwise they write nothing (no event either) and the caller reads
 * the row again. A worker whose lease expired and was taken over therefore cannot record a late outcome over the new holder's.
 */
public interface GraphRoundRepository {

    /** Creates the slot row at {@code scheduled}; the slot must not exist yet. */
    GraphRound create(String roundId, Instant slotAt, String startedBy, Instant now);

    Optional<GraphRound> find(String roundId);

    Optional<GraphRound> findBySlot(Instant slotAt);

    /** Open rounds, oldest slot first, whose next attempt is due: the scheduler's work list. */
    List<GraphRound> due(Instant now, int limit);

    /**
     * Takes the row for {@code owner} until {@code now + lease} when nobody else holds it or the holder's lease expired.
     * Empty when another instance holds it, or when the round is finished ({@code imported}, {@code skipped}); a failed round is
     * taken for its retry. A new lease (first take, or a take-over after expiry) gets a new fencing token; the holder renewing
     * an unexpired lease keeps its token.
     */
    Optional<GraphRound> claim(String roundId, String owner, Duration lease, Instant now);

    /** Gives the row back; a no-op when {@code owner} does not hold it. */
    void release(String roundId, String owner);

    /**
     * Applies the patch and appends the event in one transaction, only while the row is still at {@code expected}'s stage under
     * {@code expected}'s lease token (fenced); the lease is kept with an open stage and dropped with a terminal one. Empty when
     * the row moved on or the lease was taken over: nothing is written, and the caller reads the row again.
     *
     * @param expected the row as the caller claimed or last advanced it; must carry a lease
     * @throws IllegalArgumentException when {@code expected} carries no lease (nothing is written). The JDBC implementation is
     *                                  a Spring {@code @Repository}, so its callers receive this translated as
     *                                  {@code InvalidDataAccessApiUsageException}
     */
    Optional<GraphRound> advance(GraphRound expected, GraphRoundPatch patch, Outcome outcome, String code, String requestId,
            JsonNode detail, Instant at);

    /**
     * Records the version the round's import registers, inside the caller's transaction (the import's own, so the version and
     * the round's claim on it commit or roll back together). Fenced like {@link #advance}: false when the row moved on or the
     * lease was taken over, and nothing is written. The stage is not changed here; {@link #advance} follows after the commit.
     *
     * @throws IllegalStateException    when no transaction is active (nothing is written)
     * @throws IllegalArgumentException when {@code expected} carries no lease (nothing is written). Both reach the JDBC
     *                                  implementation's callers translated as {@code InvalidDataAccessApiUsageException}
     */
    boolean link(GraphRound expected, String graphVersionId, Instant at);

    /** R8, recorded after the fact: the auto-activation (or an admin) made the round's version public. */
    void recordActivation(String roundId, String activatedVersionId, String note, Instant at);

    /** Timeline, oldest first. */
    List<GraphRoundEvent> events(String roundId);

    /** Newest slot first; {@code beforeSlot} is the page cursor; {@code stage} narrows the list when given. */
    List<GraphRound> page(GraphRoundStage stage, Instant beforeSlot, int limit);

    /** Open (non-terminal) rounds. */
    long openCount();

    /**
     * The newest slot whose import committed: at {@code imported}, or any row with its version linked ({@link #link} committed
     * with the version; the stage change after it was lost, or a later attempt of that round failed). An older slot is never
     * imported after it.
     */
    Optional<GraphRound> newestImported();
}
