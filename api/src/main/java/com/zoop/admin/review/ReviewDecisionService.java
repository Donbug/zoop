package com.zoop.admin.review;

import com.zoop.admin.audit.AuditReasonPolicy;
import com.zoop.admin.audit.JdbcAdminIdempotencyStore;
import com.zoop.admin.auth.repository.AdminAuditRepository;
import com.zoop.admin.auth.service.AdminPrincipal;
import com.zoop.admin.review.JdbcReviewRepository.Target;
import com.zoop.admin.review.RelationReviewClient.Refused;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import java.time.Clock;
import java.time.Instant;
import org.springframework.dao.DataAccessException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

/**
 * {@code decideAnalysisCandidate} (#133, FS067-02): an administrator's {@code allow} (the final approval of a HOLD, 10-21 user
 * decision) or {@code reject} on one review target. Three steps, so no database lock is held over the AI call:
 * <ol>
 * <li>check the target and the three expected values (no lock);</li>
 * <li>send the decision to the AI source with a stable operation id (the AI source deduplicates it, so a lost reply is resent
 * with the same values and never appends twice);</li>
 * <li>under the shared publication lock, check again, then record the decision (target revision +1, global revision MAX+1), its
 * audit row and the idempotent response in one transaction.</li>
 * </ol>
 * An approval creates no job, calls no model and publishes nothing: {@code publicChanged} is always false. Only relation targets
 * can be decided: the AI source has no candidate-level review yet, so a candidate-level decision is refused (AI owner,
 * 2026-10-22: keep candidate review in the structure, do not offer it before it is connected).
 *
 * <p>Not exposed over HTTP yet: the candidate list and detail it depends on need the AI source sync (stage 4).
 */
@Service
public class ReviewDecisionService {
    private final JdbcReviewRepository reviews;
    private final JdbcAdminIdempotencyStore idempotency;
    private final AdminAuditRepository audit;
    private final RelationReviewClient source;
    private final TransactionTemplate transaction;
    private final ObjectMapper mapper;
    private final Clock clock;

    public ReviewDecisionService(JdbcReviewRepository reviews, JdbcAdminIdempotencyStore idempotency,
            AdminAuditRepository audit, RelationReviewClient source, PlatformTransactionManager transactions,
            ObjectMapper mapper, Clock clock) {
        this.reviews = reviews;
        this.idempotency = idempotency;
        this.audit = audit;
        this.source = source;
        this.transaction = new TransactionTemplate(transactions);
        this.mapper = mapper;
        this.clock = clock;
    }

    public ReviewDecision.Response decide(String candidateId, ReviewDecision.Request request, String idempotencyKey,
            AdminPrincipal admin, String requestId) {
        validateKey(idempotencyKey);
        String reason = request.reason().strip();
        if (!AuditReasonPolicy.safeMemberReason(reason)) throw new CustomException(ErrorCode.INVALID_REQUEST);
        String path = "/api/v1/admin/pipeline/candidates/" + candidateId + "/decision";
        String requestHash = requestHash(candidateId, request, reason);
        try {
            // A completed earlier request with this key replays before anything else happens.
            var earlier = idempotency.find(admin.adminId(), path, idempotencyKey, false);
            if (earlier.isPresent()) return replay(earlier.get(), requestHash);

            // 1. The target and its expected values, without a lock.
            Target target = transaction.execute(status -> resolve(candidateId, request, false));
            requireExpected(target, request);

            // 2. The AI source, outside any lock. The operation id is stable per admin and key.
            try {
                source.review(target.sourceJobId(), target.externalId(), request.expectedSourceVersion(),
                        request.expectedSourceRevision(), request.decision(), operationId(admin, idempotencyKey));
            } catch (Refused refused) {
                throw switch (refused.refusal()) {
                    case STALE, IN_FLIGHT -> new CustomException(ErrorCode.REVISION_CONFLICT);
                    case INELIGIBLE -> new CustomException(ErrorCode.VALIDATION_FAILED);
                    case UNCONFIRMED -> new CustomException(ErrorCode.SOURCE_UNAVAILABLE, true);
                };
            }

            // 3. Record under the publication lock.
            return transaction.execute(status -> record(candidateId, request, reason, path, idempotencyKey, requestHash,
                    admin, requestId));
        } catch (DataAccessException exception) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, exception);
        }
    }

    private ReviewDecision.Response record(String candidateId, ReviewDecision.Request request, String reason, String path,
            String key, String requestHash, AdminPrincipal admin, String requestId) {
        Instant now = clock.instant();
        boolean claimed = idempotency.claim(admin.adminId(), path, key, requestHash, "review_target", candidateId, now);
        var record = idempotency.find(admin.adminId(), path, key, true)
                .orElseThrow(() -> new IllegalStateException("Claimed idempotency record is missing"));
        if (!claimed) return replay(record, requestHash);

        reviews.lockPublication();
        Target target = resolve(candidateId, request, true);
        requireExpected(target, request);
        long revision = target.revision() + 1;
        long global = reviews.nextGlobalRevision();
        String status = "allow".equals(request.decision()) ? "ALLOW" : "REJECT";
        if (!reviews.advance(target.id(), target.revision(), status, now)) {
            throw new CustomException(ErrorCode.REVISION_CONFLICT);
        }
        long decisionId = reviews.insertDecision(target.id(), request.decision(), reason, admin.adminId(), admin.email(), now,
                revision, global);
        audit.recordReviewDecision(admin.adminId(), admin.email(), target.id(), decisionId, request.decision(),
                target.sourceVersion(), target.sourceRevision(), revision, global, reason, requestId, now);
        var response = new ReviewDecision.Response(candidateId, "allow".equals(request.decision()) ? "approved" : "rejected",
                revision, false);
        idempotency.complete(record.id(), 200, mapper.writeValueAsString(response));
        return response;
    }

    /** The decided target: a relation of the candidate when {@code relationId} is set; a candidate-level decision is refused. */
    private Target resolve(String candidateId, ReviewDecision.Request request, boolean lock) {
        Target candidate = reviews.currentCandidate(candidateId)
                .orElseThrow(() -> new CustomException(ErrorCode.RESOURCE_NOT_FOUND));
        if (request.relationId() == null) throw new CustomException(ErrorCode.INVALID_REQUEST);
        return reviews.currentRelation(candidate, request.relationId(), lock)
                .orElseThrow(() -> new CustomException(ErrorCode.RESOURCE_NOT_FOUND));
    }

    /** All three expected values must match, and only a HOLD can be decided (an ALLOW or a settled reject is out of scope). */
    private static void requireExpected(Target target, ReviewDecision.Request request) {
        if (target.revision() != request.expectedRevision()
                || !target.sourceVersion().equals(request.expectedSourceVersion())
                || !target.sourceRevision().equals(request.expectedSourceRevision())
                || !"HOLD".equals(target.status())) {
            throw new CustomException(ErrorCode.REVISION_CONFLICT);
        }
    }

    private ReviewDecision.Response replay(JdbcAdminIdempotencyStore.Record record, String requestHash) {
        if (!record.requestHash().equals(requestHash)) throw new CustomException(ErrorCode.IDEMPOTENCY_CONFLICT);
        if (!"completed".equals(record.status()) || record.responseBody() == null) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, true);
        }
        return mapper.readValue(record.responseBody(), ReviewDecision.Response.class);
    }

    static String requestHash(String candidateId, ReviewDecision.Request request, String reason) {
        ObjectNode body = StrictJson.newObject();
        body.put("candidateId", candidateId);
        body.put("decision", request.decision());
        body.put("reason", reason);
        body.put("relationId", request.relationId());
        body.put("expectedRevision", request.expectedRevision());
        body.put("expectedSourceVersion", request.expectedSourceVersion());
        body.put("expectedSourceRevision", request.expectedSourceRevision());
        return Canonical.digest(body);
    }

    /** The AI operation id: one per admin and key, so another admin's key can never collide with it. */
    static String operationId(AdminPrincipal admin, String key) {
        ObjectNode body = StrictJson.newObject();
        body.put("admin", admin.adminId());
        body.put("key", key);
        return "zoop-review-" + Canonical.digest(body);
    }

    private static void validateKey(String key) {
        if (key == null || key.isBlank() || key.length() > 200 || key.chars().anyMatch(Character::isISOControl)) {
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        }
    }
}
