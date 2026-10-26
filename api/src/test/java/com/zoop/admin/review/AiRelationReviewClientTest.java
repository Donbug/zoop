package com.zoop.admin.review;

import java.time.Instant;
import java.util.Optional;
import java.util.OptionalInt;

import com.zoop.admin.review.RelationReviewClient.Lookup;
import com.zoop.admin.review.RelationReviewClient.Operation;
import com.zoop.admin.review.RelationReviewClient.Refusal;
import com.zoop.admin.review.RelationReviewClient.Refused;
import com.zoop.ai.AiOperation;
import com.zoop.ai.AiTransportException;
import com.zoop.ai.RelationServiceErrorException;
import com.zoop.ai.relation.RelationClient;
import com.zoop.ai.relation.RelationDecision;
import com.zoop.ai.relation.RelationOperationStatus;
import com.zoop.ai.relation.RelationReviewRequest;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class AiRelationReviewClientTest {
    private static final String JOB = "s3-job-1";
    private static final String CANDIDATE = "rc-" + "a".repeat(64);
    private static final String VERSION = "b".repeat(64);
    private static final String OPERATION = "op-1";

    private final RelationClient relations = mock(RelationClient.class);
    private final AiRelationReviewClient client = new AiRelationReviewClient(relations);

    @Test
    void theDecisionIsSentAsTheContractsRequestUnderTheOperationId() {
        client.review(JOB, CANDIDATE, VERSION, "3", "allow", OPERATION);

        ArgumentCaptor<RelationReviewRequest> sent = ArgumentCaptor.forClass(RelationReviewRequest.class);
        verify(relations).review(eq(JOB), sent.capture());
        assertEquals(new RelationReviewRequest(OPERATION, CANDIDATE, VERSION, "3", RelationDecision.ALLOW), sent.getValue());
    }

    @Test
    void anAiErrorCodeIsGroupedByTheExistingTable() {
        for (var expected : java.util.Map.of("source_revision_conflict", Refusal.STALE, "review_candidate_ineligible",
                Refusal.INELIGIBLE, "review_call_in_flight", Refusal.BUSY, "service_busy", Refusal.UNAVAILABLE,
                "runtime_unavailable", Refusal.UNCONFIRMED, "idempotency_conflict", Refusal.CONTRACT, "something_new",
                Refusal.CONTRACT).entrySet()) {
            doThrow(rejected(AiOperation.REVIEW, expected.getKey())).when(relations).review(eq(JOB), any());
            Refused refused = assertThrows(Refused.class, () -> client.review(JOB, CANDIDATE, VERSION, "3", "reject", OPERATION));
            assertEquals(expected.getValue(), refused.refusal(), expected.getKey());
            assertEquals(expected.getKey(), refused.sourceCode());
        }
    }

    @Test
    void aFailureWithoutAnAnswerIsUnavailableWhenNeverSentUnconfirmedWhenSentAndContractWhenTheAnswerIsMalformed() {
        assertRefusal(AiTransportException.Failure.CONNECT_FAILED, Refusal.UNAVAILABLE, AiRelationReviewClient.NOT_SENT);
        assertRefusal(AiTransportException.Failure.CONNECT_TIMEOUT, Refusal.UNAVAILABLE, AiRelationReviewClient.NOT_SENT);
        assertRefusal(AiTransportException.Failure.TIMEOUT, Refusal.UNCONFIRMED, AiRelationReviewClient.UNANSWERED);
        assertRefusal(AiTransportException.Failure.IO_ERROR, Refusal.UNCONFIRMED, AiRelationReviewClient.UNANSWERED);
        assertRefusal(AiTransportException.Failure.UNEXPECTED_RESPONSE, Refusal.UNCONFIRMED, AiRelationReviewClient.UNANSWERED);
        assertRefusal(AiTransportException.Failure.RESPONSE_MALFORMED, Refusal.CONTRACT, AiRelationReviewClient.MALFORMED);
    }

    @Test
    void aStoredCommandThatDoesNotFitTheContractIsADefiniteRefusalAndIsNeverSent() {
        for (Runnable invalid : java.util.List.<Runnable>of(
                () -> client.review(JOB, "not-a-candidate", VERSION, "3", "allow", OPERATION),
                () -> client.review(JOB, CANDIDATE, VERSION, "0", "allow", OPERATION),
                () -> client.review(JOB, CANDIDATE, VERSION, "3", "maybe", OPERATION),
                () -> client.review("bad job id", CANDIDATE, VERSION, "3", "allow", OPERATION))) {
            Refused refused = assertThrows(Refused.class, invalid::run);
            assertEquals(Refusal.INELIGIBLE, refused.refusal(), "closed: nothing was recorded and never will be");
            assertEquals(AiRelationReviewClient.REQUEST_INVALID, refused.sourceCode());
        }
        verify(relations, never()).review(any(), any());
    }

    @Test
    void anUnreadableAnswerAfterSendingIsAContractMismatchNeverADefiniteRefusal() {
        doThrow(new IllegalArgumentException("decoded record")).when(relations).review(eq(JOB), any());
        Refused refused = assertThrows(Refused.class, () -> client.review(JOB, CANDIDATE, VERSION, "3", "allow", OPERATION));
        assertEquals(Refusal.CONTRACT, refused.refusal(), "it may be recorded: only a lookup settles it");
    }

    @Test
    void aLookupReportsTheLedgerStateAndTheCommandInTheAppsForm() {
        when(relations.operation(JOB, OPERATION)).thenReturn(status(RelationOperationStatus.ReviewState.APPLIED, Optional.empty()));
        Operation recorded = client.lookup(JOB, OPERATION);
        assertEquals(Lookup.RECORDED, recorded.state());
        assertEquals("allow", recorded.decision());
        assertTrue(recorded.currentContract());
        assertTrue(recorded.holds(JOB, CANDIDATE, "allow", VERSION, "3"));

        when(relations.operation(JOB, OPERATION)).thenReturn(status(RelationOperationStatus.ReviewState.UNCONFIRMED,
                Optional.empty()));
        assertEquals(Lookup.UNCONFIRMED, client.lookup(JOB, OPERATION).state());

        when(relations.operation(JOB, OPERATION)).thenReturn(status(RelationOperationStatus.ReviewState.APPLIED,
                Optional.of(RelationOperationStatus.Limitation.REVIEW_CONTRACT_CHANGED)));
        Operation legacy = client.lookup(JOB, OPERATION);
        assertFalse(legacy.currentContract(), "an operation of the earlier contract is history, never an approval");
        assertFalse(legacy.holds(JOB, CANDIDATE, "allow", VERSION, "3"));
    }

    @Test
    void anUnknownOperationIsNotFoundAndAnyOtherFailedLookupIsRefused() {
        // Re-stubbed with doThrow: a when(...) on a mock that already throws would throw while stubbing.
        doThrow(rejected(AiOperation.OPERATION, "operation_not_found")).when(relations).operation(JOB, OPERATION);
        assertEquals(Lookup.NOT_FOUND, client.lookup(JOB, OPERATION).state());

        doThrow(rejected(AiOperation.OPERATION, "job_not_found")).when(relations).operation(JOB, OPERATION);
        assertEquals("job_not_found", assertThrows(Refused.class, () -> client.lookup(JOB, OPERATION)).sourceCode());

        doThrow(transport(AiOperation.OPERATION, AiTransportException.Failure.TIMEOUT)).when(relations).operation(JOB, OPERATION);
        Refused unanswered = assertThrows(Refused.class, () -> client.lookup(JOB, OPERATION));
        assertEquals(AiRelationReviewClient.LOOKUP_UNANSWERED, unanswered.sourceCode(), "a read, never 'not sent'");

        assertEquals(Lookup.NOT_FOUND, client.lookup("bad job id", OPERATION).state(), "an id the contract rejects was never sent");
    }

    @Test
    void theRealClientIsUsedOnlyWhenTheAiRelationClientExists() {
        var runner = new ApplicationContextRunner().withUserConfiguration(ReviewConfiguration.class);
        runner.run(context -> assertInstanceOf(RelationReviewClient.Unconfigured.class,
                context.getBean(RelationReviewClient.class)));
        runner.withBean(RelationClient.class, () -> relations)
                .run(context -> assertInstanceOf(AiRelationReviewClient.class, context.getBean(RelationReviewClient.class)));
    }

    private void assertRefusal(AiTransportException.Failure failure, Refusal refusal, String code) {
        doThrow(transport(AiOperation.REVIEW, failure)).when(relations).review(eq(JOB), any());
        Refused refused = assertThrows(Refused.class, () -> client.review(JOB, CANDIDATE, VERSION, "3", "allow", OPERATION));
        assertEquals(refusal, refused.refusal(), failure.name());
        assertEquals(code, refused.sourceCode());
    }

    private static RelationServiceErrorException rejected(AiOperation operation, String code) {
        return new RelationServiceErrorException(operation, "req-1", 409, code, false, Optional.empty(), Optional.empty(),
                Optional.empty(), Optional.empty(), Optional.empty());
    }

    private static AiTransportException transport(AiOperation operation, AiTransportException.Failure failure) {
        return new AiTransportException(operation, "req-1", failure, OptionalInt.empty(), "IOException");
    }

    private static RelationOperationStatus status(RelationOperationStatus.ReviewState state,
            Optional<RelationOperationStatus.Limitation> limitation) {
        Instant at = Instant.parse("2026-10-26T00:00:00Z");
        return new RelationOperationStatus(OPERATION, JOB, CANDIDATE, RelationDecision.ALLOW, "reviewer", VERSION, "3",
                new RelationOperationStatus.Review(state, Optional.empty(), Optional.empty()),
                new RelationOperationStatus.Revalidation(RelationOperationStatus.RevalidationState.NOT_REQUESTED, 0,
                        Optional.empty(), Optional.empty(), Optional.empty(), Optional.empty(), Optional.empty()),
                RelationOperationStatus.Next.NONE, limitation, at, at, Optional.empty());
    }
}
