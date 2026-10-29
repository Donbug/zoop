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
     * Empty when another instance holds it.
     */
    Optional<GraphRound> claim(String roundId, String owner, Duration lease, Instant now);

    /** Gives the row back; a no-op when {@code owner} does not hold it. */
    void release(String roundId, String owner);

    /** Applies the patch and appends the event in one transaction; the lease is kept. */
    GraphRound advance(String roundId, GraphRoundPatch patch, Outcome outcome, String code, String requestId, JsonNode detail,
            Instant at);

    /** R8, recorded after the fact: the auto-activation (or an admin) made the round's version public. */
    void recordActivation(String roundId, String activatedVersionId, String note, Instant at);

    /** Timeline, oldest first. */
    List<GraphRoundEvent> events(String roundId);

    /** Newest slot first; {@code beforeSlot} is the page cursor; {@code stage} narrows the list when given. */
    List<GraphRound> page(GraphRoundStage stage, Instant beforeSlot, int limit);

    /** Open (non-terminal) rounds. */
    long openCount();

    /** The newest slot that reached {@code imported}: an older slot is never imported after it. */
    Optional<GraphRound> newestImported();
}
