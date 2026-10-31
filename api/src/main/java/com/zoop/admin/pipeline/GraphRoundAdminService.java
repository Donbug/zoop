package com.zoop.admin.pipeline;

import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.time.format.DateTimeParseException;
import java.util.Base64;
import java.util.List;

import com.zoop.admin.pipeline.GraphRoundAdminResponse.GraphRoundDetail;
import com.zoop.admin.pipeline.GraphRoundAdminResponse.GraphRoundEventOut;
import com.zoop.admin.pipeline.GraphRoundAdminResponse.GraphRoundHandoff;
import com.zoop.admin.pipeline.GraphRoundAdminResponse.GraphRoundLease;
import com.zoop.admin.pipeline.GraphRoundAdminResponse.GraphRoundList;
import com.zoop.admin.pipeline.GraphRoundAdminResponse.GraphRoundOut;
import com.zoop.admin.pipeline.GraphRoundAdminResponse.GraphRoundPlan;
import com.zoop.admin.pipeline.GraphRoundAdminResponse.GraphRoundsSection;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.graph.round.GraphRound;
import com.zoop.graph.round.GraphRoundEvent;
import com.zoop.graph.round.GraphRoundRepository;
import com.zoop.graph.round.GraphRoundStage;
import com.zoop.graph.round.GraphRoundStatus;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.dao.DataAccessException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * {@code listGraphRounds}, {@code getGraphRound} and the overview's {@code rounds} section (A-ADM-03, #55): the round rows and
 * their timelines, read-only. Rows are immutable in identity and ordered by slot, so the list cursor is the last slot shown.
 */
@Service
public class GraphRoundAdminService {
    static final int DEFAULT_LIMIT = 20;
    static final int MAX_LIMIT = 100;
    static final int RECENT = 10;
    private static final String CURSOR_PREFIX = "slot:";

    private final GraphRoundRepository rounds;
    private final ObjectProvider<GraphRoundStatus> status;

    public GraphRoundAdminService(GraphRoundRepository rounds, ObjectProvider<GraphRoundStatus> status) {
        this.rounds = rounds;
        this.status = status;
    }

    @Transactional(readOnly = true)
    public GraphRoundList list(String stage, String cursor, Integer requestedLimit) {
        GraphRoundStage filter = null;
        if (stage != null) {
            try {
                filter = GraphRoundStage.parse(stage);
            } catch (IllegalArgumentException unknown) {
                throw new CustomException(ErrorCode.INVALID_REQUEST);
            }
        }
        if (requestedLimit != null && (requestedLimit < 1 || requestedLimit > MAX_LIMIT)) {
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        }
        int limit = requestedLimit == null ? DEFAULT_LIMIT : requestedLimit;
        Instant before = decodeCursor(cursor);
        try {
            List<GraphRound> rows = rounds.page(filter, before, limit + 1);
            boolean hasNext = rows.size() > limit;
            List<GraphRound> items = hasNext ? rows.subList(0, limit) : rows;
            String next = hasNext ? encodeCursor(items.get(limit - 1).slotAt()) : null;
            return new GraphRoundList(items.stream().map(GraphRoundAdminService::out).toList(), next);
        } catch (DataAccessException unavailable) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, unavailable);
        }
    }

    @Transactional(readOnly = true)
    public GraphRoundDetail get(String roundId) {
        if (roundId == null || !roundId.matches("round-[0-9]{8}T[0-9]{4}")) {
            throw new CustomException(ErrorCode.RESOURCE_NOT_FOUND);
        }
        try {
            GraphRound round = rounds.find(roundId).orElseThrow(() -> new CustomException(ErrorCode.RESOURCE_NOT_FOUND));
            List<GraphRoundEventOut> events = rounds.events(roundId).stream().map(GraphRoundAdminService::out).toList();
            return new GraphRoundDetail(out(round), events);
        } catch (DataAccessException unavailable) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, unavailable);
        }
    }

    /** For the overview, inside its transaction; a data failure is the overview's to report. */
    public GraphRoundsSection section() {
        GraphRoundStatus scheduler = status.getIfAvailable(() -> GraphRoundStatus.DISABLED);
        return new GraphRoundsSection(scheduler.enabled(), scheduler.nextSlotAt().map(Instant::toString).orElse(null),
                scheduler.lastTickAt().map(Instant::toString).orElse(null), rounds.openCount(),
                rounds.page(null, null, RECENT).stream().map(GraphRoundAdminService::out).toList());
    }

    static GraphRoundOut out(GraphRound r) {
        return new GraphRoundOut(r.roundId(), r.slotAt().toString(), r.stage().wire(), r.startedBy(), r.attempts(),
                r.nextAttemptAt().map(Instant::toString).orElse(null),
                r.planId().isEmpty() && r.planDigest().isEmpty() ? null
                        : new GraphRoundPlan(r.planId().orElse(null), r.planDigest().orElse(null)),
                r.analysisJobId().orElse(null),
                r.handoffId().isEmpty() ? null
                        : new GraphRoundHandoff(r.handoffId().orElse(null), r.manifestDigest().orElse(null), r.bundleDigest().orElse(null)),
                r.graphVersionId().orElse(null), r.activatedVersionId().orElse(null), r.activationNote().orElse(null),
                r.failureCode().orElse(null),
                r.lease().map(l -> new GraphRoundLease(l.owner(), l.until().toString())).orElse(null),
                r.createdAt().toString(), r.updatedAt().toString());
    }

    static GraphRoundEventOut out(GraphRoundEvent e) {
        return new GraphRoundEventOut(e.id(), e.at().toString(), e.stage().wire(), e.outcome().wire(), e.code().orElse(null),
                e.requestId().orElse(null), e.detail().orElse(null));
    }

    /** The cursor is the last slot returned; rows never move between slots, so it stays valid. */
    private static Instant decodeCursor(String cursor) {
        if (cursor == null) return null;
        try {
            String raw = new String(Base64.getUrlDecoder().decode(cursor), StandardCharsets.UTF_8);
            if (!raw.startsWith(CURSOR_PREFIX)) throw new IllegalArgumentException();
            return Instant.parse(raw.substring(CURSOR_PREFIX.length()));
        } catch (IllegalArgumentException | DateTimeParseException exception) {
            throw new CustomException(ErrorCode.INVALID_CURSOR, exception);
        }
    }

    private static String encodeCursor(Instant slotAt) {
        return Base64.getUrlEncoder().withoutPadding().encodeToString((CURSOR_PREFIX + slotAt).getBytes(StandardCharsets.UTF_8));
    }
}
