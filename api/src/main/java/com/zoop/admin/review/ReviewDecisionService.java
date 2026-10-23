package com.zoop.admin.review;

import com.zoop.admin.audit.AuditReasonPolicy;
import com.zoop.admin.audit.JdbcAdminIdempotencyStore;
import com.zoop.admin.auth.repository.AdminAuditRepository;
import com.zoop.admin.auth.service.AdminPrincipal;
import com.zoop.admin.review.JdbcReviewRepository.Intent;
import com.zoop.admin.review.JdbcReviewRepository.Target;
import com.zoop.admin.review.RelationReviewClient.Lookup;
import com.zoop.admin.review.RelationReviewClient.Refused;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import java.time.Clock;
import java.time.Instant;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DataAccessException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

/**
 * {@code decideAnalysisCandidate} (#133, FS067-02): an administrator's {@code allow} (the final approval of a HOLD, 10-21 user
 * decision) or {@code reject} on one review target. No database lock is held over the AI call:
 * <ol>
 * <li>check the target and the three expected values (no lock; a mismatch stores and sends nothing);</li>
 * <li>in its own transaction, claim the idempotency key and write the decision intent (operation id, target, request), so the
 * app keeps a durable record of what it is about to ask before the AI source can apply it;</li>
 * <li>send the decision to the AI source under that operation id (the source deduplicates it, so a retry never appends
 * twice);</li>
 * <li>settle: under the shared publication lock, the decision (target revision +1, global revision MAX+1), its audit row, the
 * intent and the idempotent response in one transaction.</li>
 * </ol>
 * Once the AI source has applied a decision it is settled from the intent alone, whatever the projection says by then: the
 * source, not the projection, decides whether the decision exists. A definite refusal closes the intent and the key replays it;
 * an unconfirmed or temporary answer keeps the intent open, so the same key resends the same request and {@link #reconcile}
 * settles what was applied without the administrator.
 *
 * <p>An approval creates no job, calls no model and publishes nothing: {@code publicChanged} is always false. Only relation targets
 * can be decided: the AI source has no candidate-level review yet, so a candidate-level decision is refused (AI owner,
 * 2026-10-22: keep candidate review in the structure, do not offer it before it is connected).
 *
 * <p>Not exposed over HTTP yet: the candidate list and detail it depends on need the AI source sync (stage 4), which also
 * schedules {@link #reconcile}.
 */
@Service
public class ReviewDecisionService {
    private static final Logger log = LoggerFactory.getLogger(ReviewDecisionService.class);
    private static final String METHOD = "POST";

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
            // An earlier request with this key replays or resumes before anything else happens.
            var earlier = idempotency.find(admin.adminId(), path, idempotencyKey, false);
            if (earlier.isPresent()) return resume(earlier.get(), requestHash);

            // 1. The target and its expected values, without a lock.
            Target target = transaction.execute(status -> resolve(candidateId, request));
            requireExpected(target, request);

            // 2. The durable intent, committed before the AI source is asked.
            Intent intent = transaction.execute(status -> open(candidateId, target, request, reason, path, idempotencyKey,
                    requestHash, admin, requestId));
            if (intent == null) {
                // A concurrent request with the same key claimed it first.
                return resume(idempotency.find(admin.adminId(), path, idempotencyKey, false)
                        .orElseThrow(() -> new IllegalStateException("Claimed idempotency record is missing")), requestHash);
            }

            // 3 and 4.
            return send(intent);
        } catch (DataAccessException exception) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, exception);
        }
    }

    /**
     * Settles open intents created before {@code before} from the AI ledger: a recorded operation becomes its decision, an
     * unconfirmed one is resent (the source never appends twice), and an operation the source never saw is left alone, since
     * only the administrator's own retry may send a decision. Intents are taken least recently looked at first, and each one
     * left open goes to the back, so intents that never settle cannot keep the others out of a batch. One intent's failure
     * never stops the rest. Returns how many were settled.
     */
    public int reconcile(Instant before, int limit) {
        int settled = 0;
        for (Intent intent : reviews.openIntents(before, limit)) {
            try {
                Lookup lookup = source.lookup(intent.sourceJobId(), intent.operationId());
                if (lookup == Lookup.RECORDED) {
                    settle(intent.id());
                    settled++;
                    continue;
                }
                if (lookup == Lookup.UNCONFIRMED && "pending".equals(intent.status())) {
                    send(intent);
                    settled++;
                    continue;
                }
                reviews.touch(intent.id(), clock.instant());
            } catch (RuntimeException exception) {
                log.warn("Review intent {} is still open: {}", intent.id(), exception.toString());
                try {
                    reviews.touch(intent.id(), clock.instant());
                } catch (RuntimeException ignored) {
                    // The next run takes it again; nothing else depends on the order.
                }
            }
        }
        return settled;
    }

    private Intent open(String candidateId, Target target, ReviewDecision.Request request, String reason, String path,
            String key, String requestHash, AdminPrincipal admin, String requestId) {
        Instant now = clock.instant();
        if (!idempotency.claim(admin.adminId(), path, key, requestHash, "review_target", candidateId, now)) return null;
        var record = idempotency.find(admin.adminId(), path, key, true)
                .orElseThrow(() -> new IllegalStateException("Claimed idempotency record is missing"));
        Intent intent = new Intent(UUID.randomUUID().toString(), operationId(admin.adminId(), path, key), record.id(),
                admin.adminId(), admin.email(), requestId, candidateId, target.id(), target.sourceJobId(), target.externalId(),
                request.decision(), reason, request.expectedRevision(), request.expectedSourceVersion(),
                request.expectedSourceRevision(), "pending", null, null, now);
        reviews.insertIntent(intent);
        return intent;
    }

    /** The AI call for an open intent, then its settlement or the refusal's outcome. */
    private ReviewDecision.Response send(Intent intent) {
        try {
            source.review(intent.sourceJobId(), intent.relationCandidateId(), intent.expectedSourceVersion(),
                    intent.expectedSourceRevision(), intent.decision(), intent.operationId());
        } catch (Refused refused) {
            return refused(intent, refused);
        }
        return settle(intent.id());
    }

    /**
     * What the app may conclude from a refusal. Only a definite one closes the intent (the source recorded nothing and never
     * will for this request); nothing else is ever reported as a settled refusal, since the decision may still be applied.
     * When a concurrent request with the same key settled the intent meanwhile, its outcome is the answer instead.
     */
    private ReviewDecision.Response refused(Intent intent, Refused refused) {
        String code = refused.sourceCode();
        return switch (refused.refusal()) {
            case STALE -> close(intent, "refused", code, ErrorCode.REVISION_CONFLICT, false);
            case INELIGIBLE -> close(intent, "refused", code, ErrorCode.VALIDATION_FAILED, false);
            // Recorded nothing now: the same key sends the same request again later.
            case BUSY -> close(intent, "pending", code, ErrorCode.REVISION_CONFLICT, true);
            case UNAVAILABLE, UNCONFIRMED -> close(intent, "pending", code, ErrorCode.SOURCE_UNAVAILABLE, true);
            // Cannot be read either way: never resent, settled only by an operation lookup.
            case CONTRACT -> close(intent, "blocked", code, ErrorCode.INTERNAL_ERROR, false);
        };
    }

    /**
     * Moves a pending intent to {@code status} with the source code and throws {@code error}; a refused intent also fails its
     * idempotency record, so the key replays the refusal. An intent no longer pending answers with its outcome.
     */
    private ReviewDecision.Response close(Intent intent, String status, String code, ErrorCode error, boolean retryable) {
        boolean moved = Boolean.TRUE.equals(transaction.execute(tx -> {
            Intent locked = reviews.intent(intent.id(), true).orElseThrow();
            if (!"pending".equals(locked.status())) return false;
            reviews.markUnsettled(intent.id(), status, code, clock.instant());
            if ("refused".equals(status)) {
                idempotency.fail(intent.idempotencyRecordId(), error.getStatus().value(), failure(error, retryable));
            }
            return true;
        }));
        if (!moved) return replay(idempotency.findById(intent.idempotencyRecordId()).orElseThrow(), null);
        throw new CustomException(error, retryable);
    }

    /** Records the decision the AI source applied, from the intent alone; settling twice replays the first settlement. */
    private ReviewDecision.Response settle(String intentId) {
        return transaction.execute(status -> {
            reviews.lockPublication();
            Intent intent = reviews.intent(intentId, true).orElseThrow(() -> new IllegalStateException("Intent is missing"));
            if ("applied".equals(intent.status())) {
                return replay(idempotency.findById(intent.idempotencyRecordId()).orElseThrow(), null);
            }
            if ("refused".equals(intent.status())) {
                throw new IllegalStateException("The AI source applied a decision the app closed as refused: " + intentId);
            }
            Instant now = clock.instant();
            Target target = reviews.target(intent.targetId(), true)
                    .orElseThrow(() -> new IllegalStateException("Intent target is missing"));
            long revision = target.revision() + 1;
            long global = reviews.nextGlobalRevision();
            reviews.settleTarget(target.id(), target.revision(), "allow".equals(intent.decision()) ? "ALLOW" : "REJECT", now);
            long decisionId = reviews.insertDecision(target.id(), intent.decision(), intent.reason(), intent.adminId(),
                    intent.adminEmail(), now, revision, global);
            // The source version and revision the AI source checked the decision against.
            audit.recordReviewDecision(intent.adminId(), intent.adminEmail(), target.id(), decisionId, intent.decision(),
                    intent.expectedSourceVersion(), intent.expectedSourceRevision(), revision, global, intent.reason(),
                    intent.requestId(), now);
            reviews.markApplied(intent.id(), decisionId, now);
            var response = new ReviewDecision.Response(intent.candidateId(),
                    "allow".equals(intent.decision()) ? "approved" : "rejected", revision, false);
            idempotency.complete(intent.idempotencyRecordId(), 200, mapper.writeValueAsString(response));
            return response;
        });
    }

    /** An earlier request with this key: its stored outcome, or the open intent carried on. */
    private ReviewDecision.Response resume(JdbcAdminIdempotencyStore.Record record, String requestHash) {
        if (!record.requestHash().equals(requestHash)) throw new CustomException(ErrorCode.IDEMPOTENCY_CONFLICT);
        if (!"processing".equals(record.status())) return replay(record, requestHash);
        Intent intent = reviews.intentForRecord(record.id(), false)
                .orElseThrow(() -> new CustomException(ErrorCode.SOURCE_UNAVAILABLE, true));
        if ("pending".equals(intent.status())) return send(intent);
        // Settled since the record was read (applied and refused commit with their record): replay what was stored.
        if (!"blocked".equals(intent.status())) {
            return replay(idempotency.findById(intent.idempotencyRecordId()).orElseThrow(), null);
        }
        // Blocked: only the ledger can say whether it was applied.
        Lookup lookup;
        try {
            lookup = source.lookup(intent.sourceJobId(), intent.operationId());
        } catch (Refused refused) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, true);
        }
        if (lookup == Lookup.RECORDED) return settle(intent.id());
        throw new CustomException(ErrorCode.INTERNAL_ERROR);
    }

    /** A completed record's response, or a failed record's error. {@code requestHash} null: already checked. */
    private ReviewDecision.Response replay(JdbcAdminIdempotencyStore.Record record, String requestHash) {
        if (requestHash != null && !record.requestHash().equals(requestHash)) {
            throw new CustomException(ErrorCode.IDEMPOTENCY_CONFLICT);
        }
        if ("failed".equals(record.status()) && record.responseBody() != null) {
            var failure = mapper.readTree(record.responseBody());
            throw new CustomException(ErrorCode.valueOf(failure.get("code").asString()), failure.get("retryable").asBoolean());
        }
        if (!"completed".equals(record.status()) || record.responseBody() == null) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, true);
        }
        return mapper.readValue(record.responseBody(), ReviewDecision.Response.class);
    }

    private String failure(ErrorCode error, boolean retryable) {
        ObjectNode body = StrictJson.newObject();
        body.put("code", error.name());
        body.put("retryable", retryable);
        return mapper.writeValueAsString(body);
    }

    /** The decided target: a relation of the candidate when {@code relationId} is set; a candidate-level decision is refused. */
    private Target resolve(String candidateId, ReviewDecision.Request request) {
        Target candidate = reviews.currentCandidate(candidateId)
                .orElseThrow(() -> new CustomException(ErrorCode.RESOURCE_NOT_FOUND));
        if (request.relationId() == null) throw new CustomException(ErrorCode.INVALID_REQUEST);
        return reviews.currentRelation(candidate, request.relationId())
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

    /**
     * The AI operation id: the app's whole idempotency scope (admin, method, path, key), so a key the app accepts for two
     * targets is two operations in the AI source, and another admin's key never collides with it.
     */
    static String operationId(String adminId, String path, String key) {
        ObjectNode body = StrictJson.newObject();
        body.put("admin", adminId);
        body.put("method", METHOD);
        body.put("path", path);
        body.put("key", key);
        return "zoop-review-" + Canonical.digest(body);
    }

    private static void validateKey(String key) {
        if (key == null || key.isBlank() || key.length() > 200 || key.chars().anyMatch(Character::isISOControl)) {
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        }
    }
}
