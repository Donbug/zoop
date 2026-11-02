package com.zoop.admin.briefings;

import com.zoop.admin.audit.AuditReasonPolicy;
import com.zoop.admin.audit.JdbcAdminIdempotencyStore;
import com.zoop.admin.auth.service.AdminPrincipal;
import com.zoop.briefing.storage.BriefingRound;
import com.zoop.briefing.storage.BriefingRoundRepository;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Instant;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

/** One transaction for the idempotent response, row-serialized change, state and audit. No model/generation dependencies. */
@Service
public class AdminBriefingChangeService {
    private final JdbcTemplate jdbc;
    private final JdbcAdminIdempotencyStore keys;
    private final BriefingRoundRepository rounds;
    private final AdminBriefingService reads;
    private final ObjectMapper mapper;
    private final Clock clock;

    public AdminBriefingChangeService(JdbcTemplate jdbc, JdbcAdminIdempotencyStore keys,
            BriefingRoundRepository rounds, AdminBriefingService reads, ObjectMapper mapper, Clock clock) {
        this.jdbc = jdbc; this.keys = keys; this.rounds = rounds; this.reads = reads;
        this.mapper = mapper; this.clock = clock;
    }

    @Transactional
    public ObjectNode correct(String id, AdminBriefingChangeController.Correction body, String key,
            AdminPrincipal admin, String requestId) {
        String reason = reason(body.reason());
        String text = body.correctedText().strip();
        if (text.isEmpty() || text.length() > 2000 || text.codePoints().anyMatch(c -> Character.isISOControl(c) && c != '\n' && c != '\t'))
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        if (body.eventId() != null && body.eventId().isBlank()) throw new CustomException(ErrorCode.INVALID_REQUEST);
        ObjectNode command = mapper.createObjectNode().put("eventId", body.eventId()).put("correctedText", text).put("reason", reason);
        var claim = claim(id, "corrections", command, key, admin);
        if (claim.response() != null) return claim.response();
        BriefingRound round = lock(id);
        String original = null;
        if (body.eventId() != null) {
            JsonNode found = null;
            for (JsonNode item : round.payload().path("items"))
                if (body.eventId().equals(item.path("eventId").asText())) found = item;
            if (found == null) throw new CustomException(ErrorCode.INVALID_REQUEST);
            original = found.path("summary").path("text").asText(found.path("title").asText(null));
        }
        Instant now = clock.instant().truncatedTo(java.time.temporal.ChronoUnit.MICROS);
        int seq = next(id, "correction");
        Long changeId = jdbc.queryForObject("""
                INSERT INTO briefing_changes(round_id,kind,seq,event_id,original,corrected,reason,admin_id,admin_email_snapshot,created_at)
                VALUES(?,'correction',?,?,?,?,?,?,?,?) RETURNING id
                """, Long.class, id, seq, body.eventId(), original, text, reason, admin.adminId(), admin.email(), Timestamp.from(now));
        audit(id, changeId, "correct", round.status(), round.status(), reason, admin, requestId, now);
        ObjectNode response = mapper.createObjectNode().put("id", changeId).put("seq", seq).put("eventId", body.eventId())
                .put("original", original).put("corrected", text).put("reason", reason).put("createdAt", now.toString()).put("adminEmail", admin.email());
        keys.complete(claim.id(), 201, mapper.writeValueAsString(response));
        return response;
    }

    @Transactional
    public ObjectNode suspend(String id, AdminBriefingChangeController.Suspension body, String key,
            AdminPrincipal admin, String requestId) {
        String reason = reason(body.reason());
        if (!"suspend".equals(body.action()) && !"resume".equals(body.action())) throw new CustomException(ErrorCode.INVALID_REQUEST);
        ObjectNode command = mapper.createObjectNode().put("action", body.action()).put("reason", reason);
        var claim = claim(id, "suspension", command, key, admin);
        if (claim.response() != null) return claim.response();
        BriefingRound round = lock(id);
        boolean suspend = "suspend".equals(body.action());
        String target = suspend ? "suspended" : "published";
        if (!target.equals(round.status())) {
            Instant now = clock.instant().truncatedTo(java.time.temporal.ChronoUnit.MICROS);
            Long changeId = jdbc.queryForObject("""
                    INSERT INTO briefing_changes(round_id,kind,seq,suspended,reason,admin_id,admin_email_snapshot,created_at)
                    VALUES(?,'suspension',?,?,?,?,?,?) RETURNING id
                    """, Long.class, id, next(id, "suspension"), suspend, reason, admin.adminId(), admin.email(), Timestamp.from(now));
            jdbc.update("UPDATE briefing_rounds SET status=?,revision=revision+1 WHERE id=?", target, id);
            audit(id, changeId, body.action(), round.status(), target, reason, admin, requestId, now);
        }
        ObjectNode response = reads.detail(id);
        response.remove(java.util.List.of("published", "corrections", "attemptsLog"));
        keys.complete(claim.id(), 200, mapper.writeValueAsString(response));
        return response;
    }

    private record Claim(String id, ObjectNode response) { }
    private Claim claim(String id, String operation, ObjectNode command, String key, AdminPrincipal admin) {
        if (id.isBlank() || id.length() > 300 || id.codePoints().anyMatch(Character::isISOControl))
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        String path = "/api/v1/admin/briefings/" + id + "/" + operation;
        String hash = Canonical.digest(command);
        boolean created = keys.claim(admin.adminId(), path, key, hash, "briefing_round", id, clock.instant());
        var record = keys.find(admin.adminId(), path, key, true).orElseThrow();
        if (!hash.equals(record.requestHash())) throw new CustomException(ErrorCode.IDEMPOTENCY_CONFLICT);
        if ("completed".equals(record.status())) return new Claim(record.id(), (ObjectNode) StrictJson.parseObject(record.responseBody()).node());
        if (!created) throw new CustomException(ErrorCode.REVISION_CONFLICT);
        return new Claim(record.id(), null);
    }
    private BriefingRound lock(String id) {
        if (jdbc.queryForList("SELECT id FROM briefing_rounds WHERE id=? FOR UPDATE", id).isEmpty())
            throw new CustomException(ErrorCode.RESOURCE_NOT_FOUND);
        BriefingRound round = rounds.findById(id).orElseThrow(); // Includes the original JSONB digest check.
        if (round.publishedAt() == null || !("published".equals(round.status()) || "suspended".equals(round.status())))
            throw new CustomException(ErrorCode.REVISION_CONFLICT);
        return round;
    }
    private int next(String id, String kind) {
        return jdbc.queryForObject("SELECT COALESCE(max(seq),0)+1 FROM briefing_changes WHERE round_id=? AND kind=?", Integer.class, id, kind);
    }
    private static String reason(String raw) {
        String value = raw.strip();
        if (value.length() > 500 || !AuditReasonPolicy.safeMemberReason(value)) throw new CustomException(ErrorCode.INVALID_REQUEST);
        return value;
    }
    private void audit(String id, long changeId, String action, String before, String after, String reason,
            AdminPrincipal admin, String requestId, Instant at) {
        jdbc.update("""
                INSERT INTO audit_logs(actor_kind,admin_id,actor_id,actor_email_snapshot,action,target_type,target_id,
                    outcome,purpose,reason,request_id,detail,occurred_at)
                VALUES('admin',?,?,?,?,'briefing_round',?,'succeeded','briefing_publication',?,?,
                    jsonb_build_object('changeId',CAST(? AS bigint),'beforeStatus',CAST(? AS text),'afterStatus',CAST(? AS text)),?)
                """, admin.adminId(), admin.adminId(), admin.email(), "briefing." + action, id, reason, requestId,
                changeId, before, after, Timestamp.from(at));
    }
}
