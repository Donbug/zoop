package com.zoop.ai.http;

import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.regex.Pattern;

import com.zoop.ai.PipelineJob;
import com.zoop.ai.http.WireJson.Malformed;
import com.zoop.ai.http.WireJson.Obj;
import com.zoop.ai.relation.RelationDecision;
import com.zoop.ai.relation.RelationJobStatus;
import com.zoop.ai.relation.RelationOperationStatus;
import com.zoop.ai.relation.RelationOperationStatus.Revalidation;
import com.zoop.ai.relation.RelationOperationStatus.RevalidationState;
import com.zoop.ai.relation.RelationOperationStatus.Review;
import com.zoop.ai.relation.RelationOperationStatus.ReviewState;
import com.zoop.ai.relation.RelationResult;
import com.zoop.ai.relation.RelationReviewRequest;
import com.zoop.ai.relation.RelationUpstream;
import com.zoop.ai.relation.UntrustedRelationPayload;
import tools.jackson.databind.JsonNode;

/** Typed decoding of the S3 relation documents (schema {@code zoop-ai-internal-relation-1}). Fails closed with {@link Malformed}. */
final class RelationWire {
    static final String SCHEMA = "zoop-ai-internal-relation-1";
    private static final Pattern UPSTREAM_ID = RelationUpstream.JOB_ID;
    private static final Pattern PRINCIPAL = Pattern.compile("[a-z][a-z0-9-]{0,62}");
    /** A runtime chain revision as decimal text; a candidate with no event yet is 0. */
    private static final Pattern SOURCE_REVISION = Pattern.compile("0|[1-9][0-9]{0,8}");
    private static final int MAX_RELATIONS = 100_000;

    private RelationWire() {
    }

    /** {@code RelationJobStatus}: every key required, identity bound to the requested job. */
    static RelationJobStatus status(JsonNode node, String path, String expectedJobId, Optional<Duration> retryAfter) {
        Obj root = Obj.of(node, path);
        PipelineWire.schema(root, SCHEMA);
        String jobId = PipelineWire.jobId(root, expectedJobId);
        Obj usage = root.object("usage");
        Obj upstream = root.object("upstream");
        PipelineJob.State state = root.choice("state", PipelineWire.parser(PipelineJob.State.class));
        PipelineJob.Delivery delivery = PipelineWire.delivery(root.object("delivery"));
        PipelineWire.requireDeliveryFitsState(root, state, delivery);
        PipelineJob.Provenance provenance = PipelineWire.provenance(root.object("provenance"));
        return new RelationJobStatus(
                jobId,
                root.string("inputDigest", Obj.SHA256),
                provenance.sourceKind(),
                provenance.executionMode(),
                new RelationUpstream(upstream.string("jobId", UPSTREAM_ID), upstream.string("inputDigest", Obj.SHA256)),
                state,
                root.string("phase", Obj.SAFE),
                root.choice("resumeMode", PipelineWire.parser(PipelineJob.ResumeMode.class)),
                PipelineWire.failure(root),
                new RelationJobStatus.Usage(usage.count("replayCalls"), usage.count("startedWithoutReceipt"), usage.count("providerCalls"),
                        usage.count("modelCalls")),
                delivery,
                PipelineWire.dispatch(root.object("dispatch")),
                root.choice("next", PipelineWire.parser(PipelineJob.Next.class)),
                AnalysisWire.stamp(root, "acceptedAt"),
                AnalysisWire.stamp(root, "observedAt"),
                retryAfter);
    }

    /** {@code RelationResultEnvelope}. The job content is present exactly when delivery is {@code available}. */
    static RelationResult result(JsonNode node, String expectedJobId, Optional<Duration> retryAfter) {
        Obj root = Obj.of(node, "result");
        PipelineWire.schema(root, SCHEMA);
        RelationJobStatus status = status(root.raw("status"), "result.status", expectedJobId, retryAfter);
        PipelineJob.Delivery delivery = PipelineWire.delivery(root.object("delivery"));
        if (!delivery.equals(status.delivery())) {
            throw new Malformed("result.delivery");
        }
        Optional<Obj> job = root.optObject("job");
        if ((delivery.state() == PipelineJob.DeliveryState.AVAILABLE) != job.isPresent()) {
            throw new Malformed("result.job");
        }
        return new RelationResult(status, delivery, job.map(content -> payload(content, status)), PipelineWire.receipts(root));
    }

    private static UntrustedRelationPayload payload(Obj job, RelationJobStatus status) {
        if (!status.jobId().equals(job.string("jobId", Obj.PRINTABLE)) || !status.inputDigest().equals(job.string("inputDigest", Obj.SHA256))) {
            throw new Malformed("result.job");
        }
        job.object("counts");
        List<UntrustedRelationPayload.Candidate> candidates = new ArrayList<>();
        for (JsonNode item : job.array("relations", MAX_RELATIONS)) {
            Obj relation = Obj.of(item, "result.job.relations[]");
            String sourceVersion = relation.string("sourceVersion", Obj.SHA256);
            if (!sourceVersion.equals(status.inputDigest())) {
                throw new Malformed("result.job.relations[].sourceVersion");
            }
            candidates.add(new UntrustedRelationPayload.Candidate(
                    relation.string("relationCandidateId", RelationReviewRequest.CANDIDATE_ID), sourceVersion,
                    relation.string("sourceRevision", SOURCE_REVISION)));
        }
        return new UntrustedRelationPayload(status.jobId(), status.inputDigest(), WireJson.compact(job.node()), candidates);
    }

    /**
     * {@code RelationOperationStatus}: every key required, bound to the requested job and operation id, and internally coherent. A
     * current-contract operation requested no revalidation (its revalidation phase is {@code not_requested} whatever the decision) and is
     * terminal once recorded ({@code next=none}; an unconfirmed review says {@code retry_review}). Only an operation that carries the
     * {@code review_contract_changed} limitation (recorded under the earlier contract) may show another phase, and then it is history:
     * {@code verified}/{@code superseded} (a settlement at {@code expected + 2}) or {@code contract_changed}, never anything to wait for.
     */
    static RelationOperationStatus operation(JsonNode node, String path, String expectedJobId, String expectedOperationId,
                                             Optional<Duration> retryAfter) {
        Obj root = Obj.of(node, path);
        PipelineWire.schema(root, SCHEMA);
        PipelineWire.jobId(root, expectedJobId);
        if (!expectedOperationId.equals(root.string("operationId", Obj.PRINTABLE))) {
            throw new Malformed(path + ".operationId");
        }
        RelationDecision decision = root.choice("decision", PipelineWire.parser(RelationDecision.class));
        String version = root.string("expectedSourceVersion", Obj.SHA256);
        String revisionText = root.string("expectedSourceRevision", RelationReviewRequest.SOURCE_REVISION);
        long expected = Long.parseLong(revisionText);
        Obj reviewObj = root.object("review");
        Review review = new Review(reviewObj.choice("state", PipelineWire.parser(ReviewState.class)),
                reviewObj.optString("resultingSourceRevision", SOURCE_REVISION), optStamp(reviewObj, "recordedAt"));
        boolean applied = review.state() == ReviewState.APPLIED;
        boolean reviewCoherent = applied
                ? review.recordedAt().isPresent() && review.resultingSourceRevision().filter(Long.toString(expected + 1)::equals).isPresent()
                : review.recordedAt().isEmpty() && review.resultingSourceRevision().isEmpty();
        if (!reviewCoherent) {
            throw new Malformed(path + ".review");
        }
        Obj revObj = root.object("revalidation");
        RevalidationState state = revObj.choice("state", PipelineWire.parser(RevalidationState.class));
        Optional<RelationOperationStatus.Verdict> verdict = revObj.optChoice("verdict", PipelineWire.parser(RelationOperationStatus.Verdict.class));
        Optional<String> resulting = revObj.optString("resultingSourceRevision", SOURCE_REVISION);
        Revalidation revalidation = new Revalidation(state, revObj.count("dispatchCount"),
                revObj.optChoice("lastOutcome", PipelineWire.parser(PipelineJob.Outcome.class)),
                revObj.optString("lastRuntimeCode", Obj.SAFE), verdict, resulting, optStamp(revObj, "updatedAt"));
        Optional<RelationOperationStatus.Limitation> limitation = root.optChoice("limitation",
                PipelineWire.parser(RelationOperationStatus.Limitation.class));
        checkRevalidation(path, revalidation, limitation.isPresent(), decision, applied, expected);
        RelationOperationStatus.Next next = root.choice("next", PipelineWire.parser(RelationOperationStatus.Next.class));
        if (next != expectedNext(review, limitation.isPresent())) {
            throw new Malformed(path + ".next");
        }
        if (!"not_published".equals(root.object("publication").string("state", Obj.PRINTABLE))) {
            throw new Malformed(path + ".publication.state");
        }
        return new RelationOperationStatus(
                expectedOperationId,
                expectedJobId,
                root.string("relationCandidateId", RelationReviewRequest.CANDIDATE_ID),
                decision,
                root.string("reviewer", PRINCIPAL),
                version,
                revisionText,
                review,
                revalidation,
                next,
                limitation,
                AnalysisWire.stamp(root, "acceptedAt"),
                AnalysisWire.stamp(root, "observedAt"),
                retryAfter);
    }

    private static void checkRevalidation(String path, Revalidation revalidation, boolean legacy, RelationDecision decision, boolean applied, long expected) {
        RevalidationState state = revalidation.state();
        boolean settled = state == RevalidationState.VERIFIED || state == RevalidationState.SUPERSEDED;
        boolean coherent;
        if (!legacy) {
            // the current contract requests nothing: no phase, verdict or settlement, whatever the decision
            coherent = state == RevalidationState.NOT_REQUESTED && revalidation.verdict().isEmpty() && revalidation.resultingSourceRevision().isEmpty();
        } else {
            boolean historicalAllow = decision == RelationDecision.ALLOW && applied;
            coherent = (state != RevalidationState.NOT_REQUESTED) == historicalAllow
                    && (state == RevalidationState.VERIFIED) == revalidation.verdict().isPresent()
                    && settled == revalidation.resultingSourceRevision().isPresent()
                    && revalidation.resultingSourceRevision().map(v -> v.equals(Long.toString(expected + 2))).orElse(true);
        }
        if (!coherent) {
            throw new Malformed(path + ".revalidation");
        }
    }

    /** The service's rule for what the caller does next (relation_review.next_operation_action): a legacy operation has nothing to do, an unproven review is repeated. */
    private static RelationOperationStatus.Next expectedNext(Review review, boolean legacy) {
        return legacy || review.state() == ReviewState.APPLIED ? RelationOperationStatus.Next.NONE : RelationOperationStatus.Next.RETRY_REVIEW;
    }

    /**
     * A successful {@code review} answer is a recorded decision: always HTTP 200, whether the decision was just recorded (an allow is the
     * final approval, a reject an exclusion) or the same key and body replayed an existing operation (a legacy one included). Anything
     * unproven is not a recorded decision.
     */
    static RelationOperationStatus reviewAccepted(RelationOperationStatus operation) {
        if (operation.review().state() != ReviewState.APPLIED) {
            throw new Malformed("operation.review");
        }
        return operation;
    }

    private static Optional<Instant> optStamp(Obj obj, String name) {
        return AnalysisWire.optStamp(obj, name);
    }

    /** The error envelope; embedded {@code status} / {@code operation} must describe the requested job and operation. */
    static PipelineWire.Rejection rejection(JsonNode node, String requestId) {
        return PipelineWire.rejection(node, SCHEMA, requestId);
    }

    static Optional<RelationJobStatus> embeddedStatus(PipelineWire.Rejection rejection, String expectedJobId, Optional<Duration> retryAfter) {
        return rejection.embedded("status").map(embedded -> status(embedded, "error.status", expectedJobId, retryAfter));
    }

    /** {@code expectedOperationId} is null on job routes, which never embed an operation: one that appears is malformed. */
    static Optional<RelationOperationStatus> embeddedOperation(PipelineWire.Rejection rejection, String expectedJobId,
                                                               String expectedOperationId, Optional<Duration> retryAfter) {
        return rejection.embedded("operation").map(embedded -> {
            if (expectedOperationId == null) {
                throw new Malformed("error.operation");
            }
            return operation(embedded, "error.operation", expectedJobId, expectedOperationId, retryAfter);
        });
    }
}
