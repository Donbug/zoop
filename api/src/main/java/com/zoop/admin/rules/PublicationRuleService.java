package com.zoop.admin.rules;

import com.zoop.admin.audit.AuditReasonPolicy;
import com.zoop.admin.auth.repository.AdminAuditRepository;
import com.zoop.admin.auth.service.AdminPrincipal;
import com.zoop.admin.rules.JdbcPublicationRuleRepository.ChangeRow;
import com.zoop.admin.rules.JdbcPublicationRuleRepository.RuleRow;
import com.zoop.admin.rules.PublicationRuleResponse.RuleChangeOut;
import com.zoop.admin.rules.PublicationRuleResponse.RuleList;
import com.zoop.admin.rules.PublicationRuleResponse.RuleOut;
import com.zoop.admin.rules.PublicationRuleResponse.SwitchRequest;
import com.zoop.admin.rules.PublicationRuleResponse.SwitchResponse;
import com.zoop.auth.service.CsrfKeyRing;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import java.time.Clock;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;
import org.springframework.dao.DataAccessException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.ObjectMapper;

/**
 * {@code listPublicationRules} (#132) and {@code setPublicationRule} (#133). A rule is an application publication policy that can
 * only keep already eligible content off the public graph: switching one never publishes a HOLD and never calls the AI service
 * (AI owner, 2026-10-22, 5-A). A switch is a PUT of the target state, so asking for the state a rule already has records
 * nothing and answers {@code idempotent=true}.
 */
@Service
public class PublicationRuleService {
    private static final int DEFAULT_LIMIT = 50;
    private static final int MAX_LIMIT = 100;
    private static final int MAX_REASON = 500;

    private final JdbcPublicationRuleRepository repository;
    private final AdminAuditRepository audit;
    private final ObjectMapper mapper;
    private final CsrfKeyRing keys;
    private final Clock clock;

    public PublicationRuleService(JdbcPublicationRuleRepository repository, AdminAuditRepository audit, ObjectMapper mapper,
            CsrfKeyRing keys, Clock clock) {
        this.repository = repository;
        this.audit = audit;
        this.mapper = mapper;
        this.keys = keys;
        this.clock = clock;
    }

    /** One snapshot (ERD v6: composed reads use one DB snapshot), so a rule's state and its history never disagree. */
    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public RuleList list(String adminId, String cursor, Integer requestedLimit) {
        if (requestedLimit != null && (requestedLimit < 1 || requestedLimit > MAX_LIMIT)) {
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        }
        var position = RuleCursor.decode(mapper, keys, cursor, adminId, requestedLimit, MAX_LIMIT);
        int limit = requestedLimit != null ? requestedLimit : position == null ? DEFAULT_LIMIT : position.limit();
        try {
            List<RuleRow> rows = repository.page(position == null ? null : position.id(), limit + 1);
            boolean hasNext = rows.size() > limit;
            List<RuleRow> page = hasNext ? rows.subList(0, limit) : rows;
            String nextCursor = hasNext ? RuleCursor.encode(mapper, keys, adminId, limit, page.get(page.size() - 1).id())
                    : null;
            return new RuleList(outs(page), clock.instant().toString(), nextCursor);
        } catch (DataAccessException exception) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, exception);
        }
    }

    /**
     * Under the shared publication lock (with graph activation and review decisions): the rule's revision +1, the app-wide
     * {@code log_revision} MAX+1, the change row and its audit row in one transaction.
     */
    @Transactional
    public SwitchResponse set(String ruleId, SwitchRequest request, AdminPrincipal admin, String requestId) {
        String reason = request.reason().strip();
        // Length first, so an oversized reason is never scanned.
        if (reason.codePointCount(0, reason.length()) > MAX_REASON || !AuditReasonPolicy.safeMemberReason(reason)) {
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        }
        boolean enabled = request.enabled();
        try {
            repository.lockPublication();
            RuleRow rule = repository.find(ruleId, true).orElseThrow(() -> new CustomException(ErrorCode.RESOURCE_NOT_FOUND));
            long reviewRevision = repository.reviewRevision();
            if (rule.enabled() == enabled) return new SwitchResponse(out(rule), true, reviewRevision);

            Instant now = clock.instant();
            long revision = rule.revision() + 1;
            long logRevision = repository.nextLogRevision();
            repository.switchRule(ruleId, revision, enabled, now);
            long changeId = repository.insertChange(ruleId, revision, logRevision, enabled, reason, admin.adminId(),
                    admin.email(), now);
            audit.recordPublicationRuleSwitch(admin.adminId(), admin.email(), ruleId, changeId, rule.enabled(), enabled,
                    revision, logRevision, reason, requestId, now);
            RuleRow after = repository.find(ruleId, false).orElseThrow(() -> new IllegalStateException("Switched rule is missing"));
            return new SwitchResponse(out(after), false, reviewRevision);
        } catch (DataAccessException exception) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, exception);
        }
    }

    private RuleOut out(RuleRow rule) {
        return outs(List.of(rule)).get(0);
    }

    private List<RuleOut> outs(List<RuleRow> rules) {
        Map<String, List<ChangeRow>> history = repository.history(rules.stream().map(RuleRow::id).toList()).stream()
                .collect(Collectors.groupingBy(ChangeRow::ruleId));
        return rules.stream().map(rule -> {
            List<ChangeRow> changes = history.getOrDefault(rule.id(), List.of());
            ChangeRow latest = changes.isEmpty() ? null : changes.get(0);
            return new RuleOut(rule.title(), rule.id(), rule.summary(), rule.enabled(), rule.defaultEnabled(),
                    latest == null ? null : latest.changedAt().toString(), latest == null ? null : latest.adminEmail(),
                    latest == null ? null : latest.reason(), null, null, null,
                    changes.stream().map(c -> new RuleChangeOut(c.id(), c.enabled(), c.reason(), c.adminEmail(),
                            c.changedAt().toString())).toList());
        }).toList();
    }
}
