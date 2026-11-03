package com.zoop.admin.transcripts;

import com.zoop.admin.audit.AuditReasonPolicy;
import com.zoop.admin.auth.service.AdminPrincipal;
import com.zoop.auth.service.CsrfKeyRing;
import com.zoop.auth.service.SignedCursor;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.json.Canonical;
import java.time.Clock;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import static com.zoop.admin.transcripts.TranscriptHttpSchemas.*;

/** FS066-03: current permission → purpose → snapshot read → masking → committed audit → response. */
@Service
public class TranscriptService {
    private static final String CURSOR_PURPOSE = "admin-transcript-cursor-v1";
    private final TranscriptReadPolicy policy;
    private final TranscriptRepository repository;
    private final TranscriptMasker masker;
    private final TranscriptAudit audit;
    private final ObjectMapper mapper;
    private final CsrfKeyRing keys;
    private final Clock clock;
    private final TransactionTemplate reads;
    private final TranscriptPseudonym pseudonyms;

    public TranscriptService(TranscriptReadPolicy policy, TranscriptRepository repository, TranscriptMasker masker,
            TranscriptAudit audit, ObjectMapper mapper, CsrfKeyRing keys, Clock clock,
            PlatformTransactionManager transactions, TranscriptPseudonym pseudonyms) {
        this.policy = policy; this.repository = repository; this.masker = masker; this.audit = audit;
        this.mapper = mapper; this.keys = keys; this.clock = clock;
        this.pseudonyms = pseudonyms;
        this.reads = new TransactionTemplate(transactions);
        this.reads.setReadOnly(true);
        this.reads.setIsolationLevel(TransactionDefinition.ISOLATION_REPEATABLE_READ);
    }

    private record ListSnapshot(long total, List<TranscriptRepository.Summary> rows) { }
    private record DetailSnapshot(TranscriptRepository.Session session, List<TranscriptRepository.Job> jobs,
            List<TranscriptRepository.Vote> votes) { }

    public record Position(String keyId, String admin, String filters, int limit, Instant asOf,
            Instant beforeAt, String beforeId) implements SignedCursor.Position { }

    public Page list(AdminPrincipal admin, String rawPurpose, String only, String cursor, Integer requestedLimit, String requestId) {
        String purpose = authorize(admin, rawPurpose, null, requestId);
        Map<String, Integer> counts = new LinkedHashMap<>();
        String filter = only == null ? "all" : only;
        int limit = requestedLimit == null ? 50 : requestedLimit;
        try {
            if (!Set.of("all", "disliked").contains(filter) || limit < 1 || limit > 100) invalid();
            String filters = Canonical.sha256(filter + ":" + purpose);
            Position position = decode(cursor, admin.adminId(), filters, requestedLimit);
            if (position != null) limit = position.limit();
            Instant asOf = position == null ? clock.instant() : position.asOf();
            int readLimit = limit;
            var snapshot = reads.execute(status -> new ListSnapshot(repository.total(filter, asOf),
                    List.copyOf(repository.list(filter, asOf, position == null ? null : position.beforeAt(),
                            position == null ? null : position.beforeId(), readLimit + 1))));
            var rows = snapshot.rows();
            List<Summary> items = new ArrayList<>();
            for (var row : rows.stream().limit(limit).toList()) {
                String masked = mask(row.preview(), row.session().owner(), counts);
                String preview = masked.substring(0, masked.offsetByCodePoints(0, Math.min(120, masked.codePointCount(0, masked.length()))));
                items.add(new Summary(row.session().id(), pseudonyms.forMember(row.session().owner().id()), "member",
                        row.session().startedAt(), row.lastAt(), row.messages(), preview, row.up(), row.down()));
            }
            String next = null;
            if (rows.size() > limit) {
                var last = rows.get(limit - 1).session();
                next = SignedCursor.encode(mapper, keys, CURSOR_PURPOSE,
                        new Position(keys.activeKeyId(), admin.adminId(), filters, limit, asOf, last.startedAt(), last.id()));
            }
            record(admin, null, purpose, "succeeded", requestId, filter, limit, items.size(), counts);
            return new Page(List.copyOf(items), next, snapshot.total());
        } catch (CustomException error) {
            if (error.getErrorCode() == ErrorCode.AUDIT_UNAVAILABLE) throw error;
            record(admin, null, purpose, error.getErrorCode() == ErrorCode.INVALID_REQUEST || error.getErrorCode() == ErrorCode.INVALID_CURSOR
                    ? "denied" : "failed", requestId, Set.of("all", "disliked").contains(filter) ? filter : null,
                    limit >= 1 && limit <= 100 ? limit : null, 0, counts);
            throw error;
        } catch (RuntimeException error) {
            record(admin, null, purpose, "failed", requestId, null, null, 0, counts);
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        }
    }

    public Detail detail(AdminPrincipal admin, String rawPurpose, String sessionId, String requestId) {
        String target = safeTarget(sessionId);
        String purpose = authorize(admin, rawPurpose, target, requestId);
        Map<String, Integer> counts = new LinkedHashMap<>();
        try {
            if (!target.equals(sessionId)) invalid();
            var snapshot = reads.execute(status -> new DetailSnapshot(
                    repository.find(sessionId).orElseThrow(() -> new CustomException(ErrorCode.RESOURCE_NOT_FOUND)),
                    List.copyOf(repository.jobs(sessionId)), List.copyOf(repository.votes(sessionId))));
            var session = snapshot.session();
            var jobs = snapshot.jobs();
            var votes = snapshot.votes();
            List<Message> messages = new ArrayList<>();
            for (var job : jobs) {
                JsonNode result = object(job.result()), failure = object(job.failure()), context = object(job.context());
                String question = mask(job.question(), session.owner(), counts);
                String answer = mask(text(result, "answer", ""), session.owner(), counts);
                String reason = "failed".equals(job.status()) ? text(failure, "message", text(failure, "reason", null)) : null;
                if (reason != null) reason = mask(reason, session.owner(), counts);
                List<String> labels = new ArrayList<>();
                if (context.has("items") && !context.path("items").isArray()) maskingFailed();
                for (var item : context.path("items")) {
                    String label = text(item, "label", null);
                    if (label != null) labels.add(mask(label, session.owner(), counts));
                }
                JsonNode citations = result.path("citations");
                if (result.has("citations") && !citations.isArray()) maskingFailed();
                long up = 0, down = 0;
                List<String> reasons = new ArrayList<>();
                for (var vote : votes) if (vote.jobId().equals(job.id())) {
                    if ("up".equals(vote.value())) up++;
                    if ("down".equals(vote.value())) down++;
                    if (vote.reason() != null) reasons.add(mask(vote.reason(), session.owner(), counts));
                }
                messages.add(new Message(job.id(), job.seq(), job.at(), question, answer,
                        job.outcome() == null ? job.status() : job.outcome(), reason, List.copyOf(labels), citations.size(),
                        new Feedback(up, down, List.copyOf(reasons))));
            }
            var detail = new Detail(session.id(), pseudonyms.forMember(session.owner().id()), "member", session.startedAt(),
                    List.copyOf(messages), new Masking(true, TranscriptMasker.RULE_NAMES, Map.copyOf(counts)));
            record(admin, target, purpose, "succeeded", requestId, null, null, messages.size(), counts);
            return detail;
        } catch (CustomException error) {
            if (error.getErrorCode() == ErrorCode.AUDIT_UNAVAILABLE) throw error;
            record(admin, target, purpose, error.getErrorCode() == ErrorCode.INVALID_REQUEST ? "denied" : "failed",
                    requestId, null, null, 0, counts);
            throw error;
        } catch (RuntimeException error) {
            record(admin, target, purpose, "failed", requestId, null, null, 0, counts);
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        }
    }

    private String authorize(AdminPrincipal admin, String rawPurpose, String target, String requestId) {
        if (admin == null) throw new CustomException(ErrorCode.AUTH_REQUIRED);
        if (!policy.allows(admin)) {
            record(admin, target, null, "denied", requestId, null, null, 0, Map.of());
            throw new CustomException(ErrorCode.ACCESS_DENIED);
        }
        String purpose = rawPurpose == null ? "" : rawPurpose.strip();
        if (rawPurpose != null && rawPurpose.codePoints().anyMatch(Character::isISOControl)
                || purpose.codePointCount(0, purpose.length()) > 200 || !AuditReasonPolicy.safeMemberReason(purpose)
                || TranscriptMasker.containsSensitive(purpose)) {
            record(admin, target, null, "denied", requestId, null, null, 0, Map.of());
            invalid();
        }
        return purpose;
    }

    private void record(AdminPrincipal admin, String target, String purpose, String outcome, String requestId,
            String only, Integer limit, int returned, Map<String, Integer> counts) {
        try { audit.record(admin, target, purpose, outcome, requestId, only, limit, returned, Map.copyOf(counts)); }
        catch (RuntimeException error) { throw new CustomException(ErrorCode.AUDIT_UNAVAILABLE); }
    }

    private Position decode(String cursor, String admin, String filters, Integer limit) {
        try {
            Position p = SignedCursor.decode(mapper, keys, CURSOR_PURPOSE, cursor, Position.class);
            if (p != null && (!admin.equals(p.admin()) || !filters.equals(p.filters()) || p.limit() < 1 || p.limit() > 100
                    || limit != null && limit != p.limit() || p.asOf() == null || p.beforeAt() == null
                    || !safeTarget(p.beforeId()).equals(p.beforeId()))) throw new IllegalArgumentException();
            return p;
        } catch (RuntimeException error) { throw new CustomException(ErrorCode.INVALID_CURSOR); }
    }

    private String mask(String value, TranscriptMasker.Owner owner, Map<String, Integer> counts) {
        try {
            var masked = masker.mask(value, owner);
            masked.counts().forEach((kind, count) -> counts.merge(kind, count, Integer::sum));
            return masked.text();
        } catch (RuntimeException error) { throw new CustomException(ErrorCode.MASKING_FAILED); }
    }

    private JsonNode object(String value) {
        try {
            if (value == null) return mapper.createObjectNode();
            var node = mapper.readTree(value);
            if (node == null || !node.isObject()) maskingFailed();
            return node;
        } catch (RuntimeException error) { throw new CustomException(ErrorCode.MASKING_FAILED); }
    }
    private static String text(JsonNode node, String field, String fallback) {
        var value = node.get(field);
        if (value == null || value.isNull()) return fallback;
        if (!value.isString()) maskingFailed();
        return value.asText();
    }
    private static String safeTarget(String id) { return id != null && id.matches("[A-Za-z0-9_-]{8,64}") ? id : "invalid-target"; }
    private static void invalid() { throw new CustomException(ErrorCode.INVALID_REQUEST); }
    private static void maskingFailed() { throw new CustomException(ErrorCode.MASKING_FAILED); }
}
