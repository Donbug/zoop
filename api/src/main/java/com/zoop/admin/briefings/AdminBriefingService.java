package com.zoop.admin.briefings;

import com.zoop.auth.service.CsrfKeyRing;
import com.zoop.briefing.storage.BriefingRoundRepository;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.json.StrictJson;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

@Service
@Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
public class AdminBriefingService {
    static final String READ_ONLY_REASON = "재처리 기능은 아직 연결되지 않았습니다.";
    private static final ZoneId KST = ZoneId.of("Asia/Seoul");
    private final JdbcAdminBriefingRepository repository;
    private final BriefingRoundRepository publications;
    private final ObjectMapper mapper;
    private final CsrfKeyRing keys;
    private final Clock clock;

    public AdminBriefingService(JdbcAdminBriefingRepository repository, BriefingRoundRepository publications,
            ObjectMapper mapper, CsrfKeyRing keys, Clock clock) {
        this.repository = repository; this.publications = publications;
        this.mapper = mapper; this.keys = keys; this.clock = clock;
    }

    public ObjectNode list(String admin, String from, String to, String cursor, Integer requestedLimit) {
        Window window = Window.parse(from, to);
        if (requestedLimit != null && (requestedLimit < 1 || requestedLimit > 100)) invalid();
        var position = AdminBriefingCursor.decode(mapper, keys, cursor, admin, from, to, requestedLimit);
        int limit = position != null ? position.limit() : requestedLimit == null ? 50 : requestedLimit;
        var rows = repository.list(window, position, limit + 1);
        ObjectNode response = mapper.createObjectNode();
        var items = response.putArray("items");
        Instant now = clock.instant();
        rows.stream().limit(limit).forEach(row -> items.add(project(row, now)));
        response.putObject("schedule").put("morning", "09:20").put("evening", "17:30").put("timezone", "Asia/Seoul");
        response.putNull("nextCursor");
        if (rows.size() > limit) {
            var last = rows.get(limit - 1);
            response.put("nextCursor", AdminBriefingCursor.encode(mapper, keys, admin, from, to, limit,
                    at(last, "scheduled_at"), (String) last.get("id")));
        }
        return response;
    }

    public ObjectNode detail(String id) {
        if (id == null || id.isBlank() || id.length() > 300 || id.codePoints().anyMatch(Character::isISOControl)) invalid();
        var rows = repository.find(id);
        if (rows.isEmpty()) throw new CustomException(ErrorCode.RESOURCE_NOT_FOUND);
        ObjectNode result = project(rows.getFirst(), clock.instant());
        // Reuse the immutable publication digest check; suspended originals remain visible to authorized admins.
        var round = publications.findById(id).orElseThrow(() -> new CustomException(ErrorCode.RESOURCE_NOT_FOUND));
        result.set("published", round.publishedAt() == null ? mapper.nullNode() : round.payload().deepCopy());
        var corrections = result.putArray("corrections");
        for (var change : repository.changes(id)) {
            ObjectNode c = corrections.addObject();
            for (String field : List.of("id", "seq", "original", "corrected", "reason")) field(c, field, change.get(field));
            field(c, "eventId", change.get("event_id")); field(c, "createdAt", at(change, "created_at"));
            field(c, "adminEmail", change.get("admin_email_snapshot"));
        }
        var attempts = result.putArray("attemptsLog");
        for (var attempt : repository.attempts(id)) {
            ObjectNode a = attempts.addObject();
            field(a, "n", attempt.get("attempt_no")); field(a, "trigger", attempt.get("trigger"));
            field(a, "startedAt", at(attempt, "started_at")); field(a, "finishedAt", at(attempt, "finished_at"));
            field(a, "status", attempt.get("status")); field(a, "failureReason", safeReason(attempt.get("failure_reason")));
            field(a, "adminEmail", attempt.get("admin_email_snapshot"));
        }
        return result;
    }

    private ObjectNode project(Map<String, Object> r, Instant now) {
        ObjectNode out = mapper.createObjectNode();
        for (String key : List.of("id", "edition", "status", "trigger", "attempts")) field(out, key, r.get(key));
        field(out, "date", r.get("round_date").toString());
        field(out, "scheduledAt", at(r, "scheduled_at"));
        ObjectNode window = out.putObject("dataWindow");
        field(window, "start", at(r, "window_from")); field(window, "end", at(r, "window_to"));
        window.put("openStart", Boolean.TRUE.equals(r.get("open_start")));
        field(out, "generatedAt", at(r, "generated_at")); field(out, "publishedAt", at(r, "published_at"));
        field(out, "graphVersion", r.get("graph_version_id")); field(out, "reviewRevision", r.get("review_revision"));
        field(out, "itemCount", r.get("item_count")); field(out, "correctionCount", r.get("correction_count"));
        field(out, "failureReason", safeReason(r.get("failure_reason")));
        out.put("delayed", Set.of("scheduled", "generating", "verifying").contains(r.get("status"))
                && at(r, "scheduled_at").isBefore(now));
        out.put("reprocessable", false).put("blockedReason", READ_ONLY_REASON);
        out.putNull("suspension");
        if (Boolean.TRUE.equals(r.get("suspended"))) {
            ObjectNode s = out.putObject("suspension");
            field(s, "reason", r.get("suspension_reason")); field(s, "at", at(r, "suspension_at"));
            field(s, "adminEmail", r.get("suspension_admin"));
        }
        ObjectNode stages = out.putObject("stages");
        JsonNode recorded = json(r.get("stages"));
        JsonNode attempt = json(r.get("attempt_stages"));
        for (String name : List.of("generate", "verify", "publish")) {
            ObjectNode stage = stages.putObject(name).put("status", "unknown").putNull("at");
            JsonNode stored = recorded.path(name);
            if (Set.of("pending", "running", "done", "failed", "skipped").contains(stored.path("status").asText())) {
                stage.put("status", stored.path("status").asText());
                if (stored.path("at").isTextual()) {
                    try { stage.put("at", Instant.parse(stored.path("at").asText()).toString()); }
                    catch (RuntimeException ignored) { /* unknown time stays null */ }
                }
            }
            Instant completed = name.equals("generate") ? at(r, "generated_at") : name.equals("publish") ? at(r, "published_at") : null;
            if (completed != null) stage.put("status", "done").put("at", completed.toString());
            else if (name.equals("generate") && "generating".equals(r.get("status"))
                    || name.equals("verify") && "verifying".equals(r.get("status"))) stage.put("status", "running");
            else if ("failed".equals(r.get("status"))) {
                String failed = attempt.path("failureStage").asText();
                if (name.equals(failed) || name.equals("verify") && failed.endsWith("verification")
                        || name.equals("generate") && failed.endsWith("generation")) stage.put("status", "failed");
            }
        }
        return out;
    }

    private JsonNode json(Object raw) { return raw == null ? mapper.createObjectNode() : StrictJson.parseObject(raw.toString()).node(); }
    private void field(ObjectNode node, String name, Object value) {
        node.set(name, value instanceof Instant instant ? mapper.valueToTree(instant.toString()) : mapper.valueToTree(value));
    }
    private static Instant at(Map<String, Object> r, String key) {
        return r.get(key) == null ? null : ((Timestamp) r.get(key)).toInstant();
    }
    private static String safeReason(Object value) {
        if (value == null) return null;
        String reason = value.toString();
        return reason.matches("[a-z_]{1,80}") ? reason : "상세 실패 사유는 보호된 서버 기록에서 확인해 주세요.";
    }
    private static void invalid() { throw new CustomException(ErrorCode.INVALID_REQUEST); }

    record Window(Instant start, Instant end, boolean exclusiveEnd) {
        static Window parse(String from, String to) {
            try {
                boolean dates = (from != null ? from : to) != null && (from != null ? from : to).matches("\\d{4}-\\d{2}-\\d{2}");
                for (String value : new String[]{from, to}) if (value != null
                        && (value.isBlank() || value.matches("\\d{4}-\\d{2}-\\d{2}") != dates)) invalid();
                Instant start = from == null ? null : dates ? LocalDate.parse(from).atStartOfDay(KST).toInstant()
                        : OffsetDateTime.parse(from).toInstant();
                Instant end = to == null ? null : dates ? LocalDate.parse(to).plusDays(1).atStartOfDay(KST).toInstant()
                        : OffsetDateTime.parse(to).toInstant();
                if (start != null && end != null && (start.isAfter(end) || dates && start.equals(end))) invalid();
                return new Window(start, end, dates);
            } catch (RuntimeException error) { throw new CustomException(ErrorCode.INVALID_REQUEST, error); }
        }
    }
}
