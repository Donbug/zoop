package com.zoop.briefing.query;

import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.time.LocalTime;
import java.time.ZoneId;
import java.util.List;
import com.zoop.briefing.storage.BriefingRound;
import com.zoop.briefing.storage.BriefingRoundRepository;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import org.springframework.dao.DataAccessException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;

@Service
public class BriefingQueryService {
    private static final ZoneId KST = ZoneId.of("Asia/Seoul");
    private static final LocalTime MORNING = LocalTime.of(9, 20);
    private static final LocalTime EVENING = LocalTime.of(17, 30);
    private final BriefingRoundRepository repository;
    private final Clock clock;
    private final BriefingContentAccess access;
    private final JsonMapper mapper = JsonMapper.builder().build();

    public BriefingQueryService(BriefingRoundRepository repository, Clock clock, BriefingContentAccess access) {
        this.repository = repository; this.clock = clock; this.access = access;
    }

    @Transactional(readOnly = true)
    public ObjectNode get(LocalDate date, String edition, String requestId) {
        if (edition != null && !List.of("morning", "evening").contains(edition)) invalid();
        var now = clock.instant().atZone(KST);
        if (date == null) {
            date = now.toLocalDate();
            if (edition == null) {
                if (!now.toLocalTime().isBefore(EVENING)) edition = "evening";
                else if (!now.toLocalTime().isBefore(MORNING)) edition = "morning";
                else { edition = "evening"; date = date.minusDays(1); }
            } else if (now.toLocalTime().isBefore(time(edition))) date = date.minusDays(1);
        } else if (edition == null) {
            edition = !now.toLocalDate().isBefore(date) && (now.toLocalDate().isAfter(date)
                    || !now.toLocalTime().isBefore(EVENING)) ? "evening" : "morning";
        }
        try {
            var row = repository.find(date, edition).orElse(null);
            if (row == null) return empty(date, edition, null, requestId, "not_ready");
            if (row.publishedAt() == null) {
                String status = switch (row.status()) {
                    case "generating", "verifying" -> "generating";
                    case "failed" -> "failed";
                    default -> "not_ready";
                };
                return empty(date, edition, row, requestId, status);
            }
            if (row.status().equals("suspended")) return empty(date, edition, row, requestId, "suspended");
            if (!access.mayRead(row)) throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
            return restore(row, requestId);
        } catch (DataAccessException e) { throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE); }
    }

    @Transactional(readOnly = true)
    public ObjectNode history(String cursor, Integer requestedLimit) {
        int limit = requestedLimit == null ? 20 : requestedLimit;
        // Local page safety bound, not an overall result cap; follow nextCursor to exhaust history.
        if (limit < 1 || limit > 100) invalid();
        var key = BriefingCursor.decode(cursor, limit);
        try {
            var rows = repository.history(key == null ? null : key.scheduledAt(), key == null ? null : key.id(), limit + 1);
            var response = mapper.createObjectNode();
            var items = response.putArray("items");
            for (var row : rows.subList(0, Math.min(limit, rows.size()))) {
                var item = items.addObject();
                item.put("id", row.id()).put("date", row.date().toString()).put("edition", row.edition())
                    .put("status", row.status()).put("publishedAt", row.publishedAt().toString());
            }
            response.put("nextCursor", rows.size() > limit ? BriefingCursor.encode(rows.get(limit - 1), limit) : null);
            return response;
        } catch (DataAccessException e) { throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE); }
    }

    private ObjectNode restore(BriefingRound row, String requestId) {
        var p = row.payload();
        if (p == null || !p.isObject() || row.publicSnapshot() == null
                || !row.publicSnapshot().has("marketSummary")) throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        var out = mapper.createObjectNode();
        for (String field : List.of("id", "date", "edition", "scheduledAt", "generatedAt", "dataWindow", "graphVersion",
                "items", "references", "emptyReason", "outlook", "metadata")) {
            if (!p.has(field)) throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
            out.set(field, p.get(field).deepCopy());
        }
        out.put("status", "published").put("publishedAt", row.publishedAt().toString());
        out.set("dataAsOf", p.path("dataWindow").path("end").deepCopy());
        out.set("marketSummary", row.publicSnapshot().get("marketSummary").deepCopy());
        JsonNode market = p.get("marketVariables");
        out.set("marketVariables", market == null || market.isNull() ? unavailable("발행 당시 시장 지표가 저장되지 않았습니다.") : market.deepCopy());
        out.set("sinceMorning", row.comparisonSnapshot() == null ? mapper.nullNode() : row.comparisonSnapshot().deepCopy());
        out.putArray("corrections"); // No correction writer is installed in this first storage slice.
        out.putNull("notice");
        if (!(out.get("metadata") instanceof ObjectNode metadata)) throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        metadata.put("requestId", requestId);
        return out;
    }

    private ObjectNode empty(LocalDate date, String edition, BriefingRound row, String requestId, String status) {
        var scheduled = row == null ? date.atTime(time(edition)).atZone(KST).toInstant() : row.scheduledAt();
        var out = mapper.createObjectNode();
        out.put("id", row == null ? "brf-" + date + "-" + edition : row.id());
        out.put("date", date.toString()).put("edition", edition).put("status", status).put("scheduledAt", scheduled.toString());
        out.put("publishedAt", row == null || row.publishedAt() == null ? null : row.publishedAt().toString());
        out.putNull("generatedAt").putNull("dataAsOf").putNull("graphVersion").putNull("outlook").putNull("emptyReason");
        if (row == null) out.putNull("dataWindow");
        else out.putObject("dataWindow").put("start", row.windowFrom() == null ? null : row.windowFrom().toString())
            .put("end", row.windowTo().toString()).put("openStart", row.openStart());
        out.putArray("items"); out.putArray("corrections");
        var refs = out.putObject("references"); refs.putArray("eventIds"); refs.putArray("evidenceIds"); refs.putArray("companyIds");
        out.set("marketSummary", unavailable("이 회차의 공개 내용을 제공하지 않습니다."));
        out.set("marketVariables", unavailable("이 회차의 공개 내용을 제공하지 않습니다.")); out.putNull("sinceMorning");
        var metadata = out.putObject("metadata");
        metadata.put("source", "zoop-briefing").put("asOf", clock.instant().toString()).putNull("graphVersion")
            .put("requestId", requestId).put("partial", false);
        metadata.putArray("failures");
        metadata.putObject("schedule").put("morning", "09:20").put("evening", "17:30").put("confirmed", true);
        metadata.putObject("selection").put("basis", "market").putNull("reason");
        String kind = status.equals("generating") ? "not_ready" : status;
        String message = switch (status) {
            case "generating" -> "브리핑을 만드는 중입니다.";
            case "failed" -> "브리핑을 준비하지 못했습니다.";
            case "suspended" -> "이 회차의 제공을 중단했습니다.";
            default -> "아직 발행 전입니다.";
        };
        out.putObject("notice").put("kind", kind).put("message", message).putNull("reason").putNull("at");
        return out;
    }
    private ObjectNode unavailable(String reason) { return mapper.createObjectNode().put("status", "unavailable").put("reason", reason); }
    private static LocalTime time(String edition) { return edition.equals("morning") ? MORNING : EVENING; }
    private static void invalid() { throw new CustomException(ErrorCode.INVALID_REQUEST); }
}
