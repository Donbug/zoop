package com.zoop.graph.round;

import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import com.zoop.graph.round.GraphRound.Lease;
import com.zoop.graph.round.GraphRoundEvent.Outcome;
import tools.jackson.databind.JsonNode;

/**
 * The round rows in memory, with the same rules as the SQL (one row per slot, append-only timeline, fencing on the lease token
 * and the expected stage). {@link #link} has no transaction of its own here: a test that needs "the link is undone with the
 * import" wraps it like the importer's double does.
 */
public final class InMemoryGraphRoundRepository implements GraphRoundRepository {
    private final Map<String, GraphRound> rows = new LinkedHashMap<>();
    private final List<GraphRoundEvent> events = new ArrayList<>();
    private long tokens;

    @Override
    public GraphRound create(String roundId, Instant slotAt, String startedBy, Instant now) {
        if (rows.containsKey(roundId) || findBySlot(slotAt).isPresent()) {
            throw new IllegalStateException("duplicate round");
        }
        GraphRound round = new GraphRound(roundId, slotAt, GraphRoundStage.SCHEDULED, Optional.empty(), Optional.empty(),
                Optional.empty(), Optional.empty(), Optional.empty(), Optional.empty(), Optional.empty(), Optional.empty(),
                Optional.empty(), Optional.empty(), Optional.empty(), 0, Optional.empty(), Optional.empty(), startedBy, now, now);
        rows.put(roundId, round);
        return round;
    }

    /** A row at a given stage with its handoff pins, as the scheduler would have left it before R7 (no lease). */
    public GraphRound seed(String roundId, Instant slotAt, GraphRoundStage stage, String handoffId, String manifestDigest,
            String bundleDigest, int attempts) {
        return seed(roundId, slotAt, stage, handoffId, manifestDigest, bundleDigest, null, attempts);
    }

    /** The same with a version already linked (an import whose stage change was lost): committed at the slot instant. */
    public GraphRound seed(String roundId, Instant slotAt, GraphRoundStage stage, String handoffId, String manifestDigest,
            String bundleDigest, String graphVersionId, int attempts) {
        GraphRound round = new GraphRound(roundId, slotAt, stage, Optional.empty(), Optional.empty(), Optional.empty(),
                Optional.ofNullable(handoffId), Optional.ofNullable(manifestDigest), Optional.ofNullable(bundleDigest),
                Optional.ofNullable(graphVersionId), graphVersionId == null ? Optional.empty() : Optional.of(slotAt),
                Optional.empty(), Optional.empty(), Optional.empty(), attempts, Optional.empty(), Optional.empty(),
                "system:scheduler", slotAt, slotAt);
        rows.put(roundId, round);
        return round;
    }

    @Override
    public Optional<GraphRound> find(String roundId) {
        return Optional.ofNullable(rows.get(roundId));
    }

    @Override
    public Optional<GraphRound> findBySlot(Instant slotAt) {
        return rows.values().stream().filter(r -> r.slotAt().equals(slotAt)).findFirst();
    }

    @Override
    public List<GraphRound> due(Instant now, int limit) {
        return rows.values().stream().filter(GraphRound::open)
                .filter(r -> r.nextAttemptAt().map(at -> !at.isAfter(now)).orElse(true))
                .sorted(Comparator.comparing(GraphRound::slotAt)).limit(limit).toList();
    }

    @Override
    public Optional<GraphRound> claim(String roundId, String owner, Duration lease, Instant now) {
        GraphRound round = rows.get(roundId);
        if (round == null || round.stage() == GraphRoundStage.IMPORTED || round.stage() == GraphRoundStage.SKIPPED) {
            return Optional.empty();
        }
        boolean free = round.lease().map(l -> l.owner().equals(owner) || l.until().isBefore(now)).orElse(true);
        if (!free) return Optional.empty();
        boolean renewal = round.lease().map(l -> l.owner().equals(owner) && !l.until().isBefore(now)).orElse(false);
        long token = renewal ? round.lease().orElseThrow().token() : ++tokens;
        GraphRound taken = with(round, round.stage(), round.failureCode().orElse(null), round.attempts(),
                round.nextAttemptAt().orElse(null), Optional.of(new Lease(owner, now.plus(lease), token)),
                round.graphVersionId().orElse(null), round.versionCommittedAt(), now);
        rows.put(roundId, taken);
        return Optional.of(taken);
    }

    @Override
    public void release(String roundId, String owner) {
        GraphRound round = rows.get(roundId);
        if (round != null && round.lease().map(l -> l.owner().equals(owner)).orElse(false)) {
            rows.put(roundId, with(round, round.stage(), round.failureCode().orElse(null), round.attempts(),
                    round.nextAttemptAt().orElse(null), Optional.empty(), round.graphVersionId().orElse(null),
                    round.versionCommittedAt(), round.updatedAt()));
        }
    }

    @Override
    public Optional<GraphRound> advance(GraphRound expected, GraphRoundPatch patch, Outcome outcome, String code,
            String requestId, JsonNode detail, Instant at) {
        GraphRound round = current(expected);
        if (round == null) return Optional.empty();
        String roundId = round.roundId();
        int attempts = (patch.resetAttempts() ? 0 : round.attempts()) + (patch.countAttempt() ? 1 : 0);
        Instant next = patch.clearNextAttempt() ? null : patch.nextAttemptAt() != null ? patch.nextAttemptAt()
                : round.nextAttemptAt().orElse(null);
        GraphRound updated = new GraphRound(roundId, round.slotAt(), patch.stage(),
                first(patch.planId(), round.planId()), first(patch.planDigest(), round.planDigest()),
                first(patch.analysisJobId(), round.analysisJobId()), first(patch.handoffId(), round.handoffId()),
                first(patch.manifestDigest(), round.manifestDigest()), first(patch.bundleDigest(), round.bundleDigest()),
                patch.clearGraphVersion() ? Optional.empty() : first(patch.graphVersionId(), round.graphVersionId()),
                round.versionCommittedAt().or(() -> Optional.ofNullable(patch.graphVersionId()).map(ignored -> at)),
                round.activatedVersionId(), round.activationNote(),
                Optional.ofNullable(patch.failureCode()), attempts, Optional.ofNullable(next),
                patch.stage().terminal() ? Optional.empty() : round.lease(), round.startedBy(), round.createdAt(), at);
        rows.put(roundId, updated);
        events.add(new GraphRoundEvent(events.size() + 1, roundId, at, patch.stage(), outcome, Optional.ofNullable(code),
                Optional.ofNullable(requestId), Optional.ofNullable(detail)));
        return Optional.of(updated);
    }

    @Override
    public boolean link(GraphRound expected, String graphVersionId, Instant at) {
        GraphRound round = current(expected);
        if (round == null) return false;
        rows.put(round.roundId(), with(round, round.stage(), round.failureCode().orElse(null), round.attempts(),
                round.nextAttemptAt().orElse(null), round.lease(), graphVersionId, round.versionCommittedAt().or(() -> Optional.of(at)),
                at));
        return true;
    }

    /** The row when it is still at the expected stage under the expected lease token, else null (fenced). */
    private GraphRound current(GraphRound expected) {
        long token = expected.lease().orElseThrow(() -> new IllegalArgumentException("the round must be claimed first")).token();
        GraphRound round = rows.get(expected.roundId());
        if (round == null) throw new IllegalStateException("round not found");
        boolean same = round.stage() == expected.stage() && round.lease().map(l -> l.token() == token).orElse(false);
        return same ? round : null;
    }

    @Override
    public void recordActivation(String roundId, String activatedVersionId, String note, Instant at) {
        GraphRound round = rows.get(roundId);
        if (round == null) return;
        rows.put(roundId, new GraphRound(roundId, round.slotAt(), round.stage(), round.planId(), round.planDigest(),
                round.analysisJobId(), round.handoffId(), round.manifestDigest(), round.bundleDigest(), round.graphVersionId(),
                round.versionCommittedAt(), Optional.ofNullable(activatedVersionId), Optional.ofNullable(note),
                round.failureCode(), round.attempts(),
                round.nextAttemptAt(), round.lease(), round.startedBy(), round.createdAt(), at));
    }

    @Override
    public List<GraphRoundEvent> events(String roundId) {
        return events.stream().filter(e -> e.roundId().equals(roundId)).toList();
    }

    @Override
    public List<GraphRound> page(GraphRoundStage stage, Instant beforeSlot, int limit) {
        return rows.values().stream().filter(r -> stage == null || r.stage() == stage)
                .filter(r -> beforeSlot == null || r.slotAt().isBefore(beforeSlot))
                .sorted(Comparator.comparing(GraphRound::slotAt).reversed()).limit(limit).toList();
    }

    @Override
    public long openCount() {
        return rows.values().stream().filter(GraphRound::open).count();
    }

    @Override
    public Optional<GraphRound> newestImported() {
        return rows.values().stream()
                .filter(r -> r.stage() == GraphRoundStage.IMPORTED || r.versionCommittedAt().isPresent())
                .max(Comparator.comparing(GraphRound::slotAt));
    }

    private static Optional<String> first(String patched, Optional<String> current) {
        return patched != null ? Optional.of(patched) : current;
    }

    private static GraphRound with(GraphRound r, GraphRoundStage stage, String failureCode, int attempts, Instant next,
            Optional<Lease> lease, String versionId, Optional<Instant> versionCommittedAt, Instant updatedAt) {
        return new GraphRound(r.roundId(), r.slotAt(), stage, r.planId(), r.planDigest(), r.analysisJobId(), r.handoffId(),
                r.manifestDigest(), r.bundleDigest(), Optional.ofNullable(versionId), versionCommittedAt, r.activatedVersionId(),
                r.activationNote(), Optional.ofNullable(failureCode), attempts, Optional.ofNullable(next), lease, r.startedBy(),
                r.createdAt(), updatedAt);
    }
}
