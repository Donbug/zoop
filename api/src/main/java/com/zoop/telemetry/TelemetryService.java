package com.zoop.telemetry;

import java.time.Clock;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.json.Canonical;
import com.zoop.telemetry.dto.TelemetryBatchRequest;
import com.zoop.telemetry.dto.TelemetryEventRequest;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.JsonNode;

@Service
public class TelemetryService {
    private static final Set<String> EVENT_TYPES = Set.of("screen_view", "graph_node_select", "graph_edge_select",
            "briefing_view", "briefing_issue_open", "ai_question");
    private static final Set<String> SCREENS = Set.of("main", "briefing", "ai");
    private final TelemetryRepository repository;
    private final Clock clock;
    private final ObjectMapper mapper;

    public TelemetryService(TelemetryRepository repository, Clock clock, ObjectMapper mapper) {
        this.repository = repository;
        this.clock = clock;
        this.mapper = mapper;
    }

    @Transactional
    public Accepted record(String principal, String idempotencyKey, TelemetryBatchRequest body, String requestId) {
        if (idempotencyKey == null || idempotencyKey.isEmpty()
                || body == null || body.events() == null || body.events().isEmpty()
                || body.events().size() > 20) throw invalid();
        var events = new ArrayList<TelemetryRepository.Event>();
        var digestEvents = new ArrayList<Map<String, Object>>();
        Instant now = clock.instant();
        for (TelemetryEventRequest event : body.events()) {
            events.add(parse(event, now));
            var digestEvent = new LinkedHashMap<String, Object>();
            digestEvent.put("type", event.type());
            digestEvent.put("screen", event.screen());
            digestEvent.put("targetId", event.targetId());
            digestEvent.put("roundId", event.roundId());
            digestEvent.put("viewId", event.viewId());
            digestEvents.add(digestEvent);
        }
        String digest = Canonical.sha256(Canonical.bytes(mapper.valueToTree(Map.of("events", digestEvents))));
        try {
            return new Accepted(repository.record(principal, idempotencyKey, digest, events, now));
        } catch (CustomException exception) {
            throw exception;
        } catch (org.springframework.dao.DataAccessException exception) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, exception);
        }
    }

    private static TelemetryRepository.Event parse(TelemetryEventRequest event, Instant now) {
        if (event == null || event.type() == null || event.viewId() == null
                || !EVENT_TYPES.contains(event.type()) || !event.isShapeValid()
                || (event.screen() != null && !SCREENS.contains(event.screen()))
                || !event.viewId().matches("[A-Za-z0-9-]{8,40}")
                || (event.targetId() != null && !event.targetId().matches("[A-Za-z0-9._:/-]+"))
                || (event.roundId() != null && !event.roundId().matches("[A-Za-z0-9._:/-]{1,256}"))) {
            throw invalid();
        }
        return new TelemetryRepository.Event(event.type(), event.screen(), event.targetId(), event.roundId(),
                event.viewId(), now);
    }

    private static CustomException invalid() { return new CustomException(ErrorCode.INVALID_REQUEST); }
    public record Accepted(int accepted) { }
}
