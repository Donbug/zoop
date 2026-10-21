package com.zoop.telemetry;

import java.time.Clock;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Set;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.json.Canonical;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.JsonNode;

@Service
public class TelemetryService {
    private static final Set<String> SCREENS = Set.of("main", "briefing", "ai");
    private final TelemetryRepository repository;
    private final Clock clock;

    public TelemetryService(TelemetryRepository repository, Clock clock) {
        this.repository = repository;
        this.clock = clock;
    }

    @Transactional
    public Accepted record(String principal, String idempotencyKey, JsonNode body, String requestId) {
        if (idempotencyKey == null || !idempotencyKey.matches("[A-Za-z0-9._:-]{8,128}")
                || body == null || !body.isObject() || body.size() != 1 || !body.has("events")
                || !body.get("events").isArray() || body.get("events").size() < 1
                || body.get("events").size() > 20) throw invalid();
        var events = new ArrayList<TelemetryRepository.Event>();
        Instant now = clock.instant();
        for (JsonNode event : body.get("events")) events.add(parse(event, now));
        String digest = Canonical.sha256(Canonical.bytes(body));
        try {
            return new Accepted(repository.record(principal, idempotencyKey, digest, events, now));
        } catch (CustomException exception) {
            throw exception;
        } catch (org.springframework.dao.DataAccessException exception) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, exception);
        }
    }

    private static TelemetryRepository.Event parse(JsonNode value, Instant now) {
        if (value == null || !value.isObject() || !value.has("type") || !value.get("type").isString()) throw invalid();
        String type = value.get("type").stringValue();
        String screen = optionalString(value, "screen");
        String target = optionalString(value, "targetId");
        String round = optionalString(value, "roundId");
        String view = requiredString(value, "viewId");
        if (!view.matches("[A-Za-z0-9-]{8,40}")) throw invalid();
        Set<String> fields = switch (type) {
            case "screen_view" -> Set.of("type", "screen", "viewId");
            case "graph_node_select", "graph_edge_select" -> Set.of("type", "targetId", "viewId");
            case "briefing_view" -> Set.of("type", "targetId", "viewId");
            case "briefing_issue_open" -> Set.of("type", "targetId", "roundId", "viewId");
            case "ai_question" -> Set.of("type", "targetId", "viewId");
            default -> throw invalid();
        };
        for (String key : value.propertyNames()) if (!fields.contains(key)) throw invalid();
        if ("screen_view".equals(type)) {
            if (!SCREENS.contains(screen) || target != null || round != null) throw invalid();
        } else if ("briefing_issue_open".equals(type)) {
            if (target == null || round == null) throw invalid();
        } else if ("ai_question".equals(type)) {
            if (round != null) throw invalid();
        } else if (target == null || round != null) throw invalid();
        if (target != null && (target.isBlank() || target.length() > 256
                || !target.matches("[A-Za-z0-9._:/-]+"))) throw invalid();
        if (round != null && (round.isBlank() || round.length() > 256)) throw invalid();
        return new TelemetryRepository.Event(type, screen, target, round, view, now);
    }

    private static String requiredString(JsonNode node, String key) {
        if (!node.has(key) || !node.get(key).isString()) throw invalid();
        return node.get(key).stringValue();
    }

    private static String optionalString(JsonNode node, String key) {
        if (!node.has(key) || node.get(key).isNull()) return null;
        if (!node.get(key).isString()) throw invalid();
        return node.get(key).stringValue();
    }

    private static CustomException invalid() { return new CustomException(ErrorCode.INVALID_REQUEST); }
    public record Accepted(int accepted) { }
}
