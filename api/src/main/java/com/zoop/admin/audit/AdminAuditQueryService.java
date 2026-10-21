package com.zoop.admin.audit;

import java.time.Clock;
import java.time.Instant;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

import com.zoop.auth.service.CsrfKeyRing;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.json.Canonical;
import org.springframework.dao.DataAccessException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.ObjectMapper;

@Service
public class AdminAuditQueryService {
    private static final int DEFAULT_LIMIT = 50;
    private static final int MAX_LIMIT = 100;
    private static final Set<String> AUTH_REASONS = Set.of("invalid_credentials", "account_blocked");

    private final AdminAuditReadRepository repository;
    private final ObjectMapper mapper;
    private final CsrfKeyRing keys;
    private final Clock clock;

    public AdminAuditQueryService(AdminAuditReadRepository repository, ObjectMapper mapper,
            CsrfKeyRing keys, Clock clock) {
        this.repository = repository;
        this.mapper = mapper;
        this.keys = keys;
        this.clock = clock;
    }

    @Transactional(readOnly = true)
    public AuditPage list(String adminId, String action, String actor, String targetType,
            String query, String cursor, Integer requestedLimit) {
        if (adminId == null || adminId.isBlank()) throw new CustomException(ErrorCode.ACCESS_DENIED);
        String normalizedAction = normalize(action, 80);
        String normalizedActor = normalize(actor, 200);
        String normalizedTargetType = normalize(targetType, 80);
        String normalizedQuery = normalize(query, 200);
        if (requestedLimit != null && (requestedLimit < 1 || requestedLimit > MAX_LIMIT)) {
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        }
        String filtersHash = Canonical.sha256(String.join("\n",
                normalizedAction == null ? "" : normalizedAction,
                normalizedActor == null ? "" : normalizedActor,
                normalizedTargetType == null ? "" : normalizedTargetType,
                normalizedQuery == null ? "" : normalizedQuery));
        Instant now = clock.instant();
        var position = AuditCursor.decode(mapper, keys, cursor, adminId,
                filtersHash, requestedLimit, now);
        int limit = requestedLimit != null ? requestedLimit
                : position == null ? DEFAULT_LIMIT : position.limit();
        Instant asOf = position == null ? now : position.asOf();
        try {
            List<AuditRecord> rows = repository.page(normalizedAction, normalizedActor,
                    normalizedTargetType, like(normalizedQuery), asOf,
                    position == null ? null : position.at(),
                    position == null ? null : position.id(), limit + 1);
            boolean hasNext = rows.size() > limit;
            List<AuditRecord> pageRows = hasNext ? rows.subList(0, limit) : rows;
            String nextCursor = null;
            if (hasNext) {
                AuditRecord last = pageRows.get(pageRows.size() - 1);
                nextCursor = AuditCursor.encode(mapper, keys, adminId, filtersHash,
                        limit, asOf, last.at(), last.id());
            }
            return new AuditPage(pageRows.stream().map(this::entry).toList(), nextCursor);
        } catch (DataAccessException exception) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, exception);
        }
    }

    private AuditPage.AuditEntry entry(AuditRecord row) {
        String outcome = switch (row.outcome()) {
            case "succeeded" -> "ok";
            case "denied", "failed" -> row.outcome();
            default -> throw new IllegalStateException("Unsupported audit outcome");
        };
        return new AuditPage.AuditEntry(row.id(), row.at(), row.actorKind(), row.actorId(),
                "admin".equals(row.actorKind()) ? row.actorEmail() : null,
                row.action(), row.targetType(), row.targetId(), publicReason(row),
                outcome, publicDetail(row));
    }

    private static String publicReason(AuditRecord row) {
        if ("auth.login_failed".equals(row.action()) && row.reason() != null
                && AUTH_REASONS.contains(row.reason())) {
            return row.reason();
        }
        if ("admin.provision".equals(row.action())
                && "email_already_registered".equals(row.reason())) return row.reason();
        if (("member.block".equals(row.action()) || "member.unblock".equals(row.action()))
                && AuditReasonPolicy.safeMemberReason(row.reason())) return row.reason();
        return null;
    }

    private Map<String, Object> publicDetail(AuditRecord row) {
        if ("admin.provision".equals(row.action())) return Map.of("role", "admin");
        if (!"member.block".equals(row.action()) && !"member.unblock".equals(row.action())) {
            return Map.of();
        }
        try {
            Map<?, ?> raw = mapper.readValue(row.detailJson(), Map.class);
            Object beforeStatus = raw.get("beforeStatus");
            Object afterStatus = raw.get("afterStatus");
            Object beforeRevision = raw.get("beforeRevision");
            Object afterRevision = raw.get("afterRevision");
            if (!(beforeStatus instanceof String before) || !(afterStatus instanceof String after)
                    || !Set.of("active", "blocked").contains(before)
                    || !Set.of("active", "blocked").contains(after)
                    || !(beforeRevision instanceof Number previous)
                    || !(afterRevision instanceof Number current)
                    || previous.longValue() < 0 || current.longValue() < 0) return Map.of();
            return Map.of("beforeStatus", before, "afterStatus", after,
                    "beforeRevision", previous.longValue(), "afterRevision", current.longValue());
        } catch (Exception exception) {
            throw new IllegalStateException("Unable to read audit detail", exception);
        }
    }

    private static String normalize(String value, int maxLength) {
        if (value == null) return null;
        String normalized = value.strip();
        if (normalized.isEmpty()) return null;
        if (normalized.length() > maxLength || normalized.chars().anyMatch(Character::isISOControl)) {
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        }
        return normalized;
    }

    private static String like(String query) {
        if (query == null) return null;
        return "%" + query.toLowerCase(Locale.ROOT)
                .replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%";
    }
}
