package com.zoop.document.evidence.service;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.stream.Stream;

import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.document.evidence.dto.EvidenceResponse;
import com.zoop.document.evidence.repository.EvidenceView;
import com.zoop.document.evidence.repository.SummaryView;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.dao.QueryTimeoutException;
import org.springframework.transaction.CannotCreateTransactionException;
import org.springframework.transaction.support.TransactionOperations;
import tools.jackson.databind.node.ObjectNode;
import tools.jackson.databind.node.ArrayNode;

import static com.zoop.document.evidence.service.EvidenceWorld.ARTICLE;
import static com.zoop.document.evidence.service.EvidenceWorld.GRANT;
import static com.zoop.document.evidence.service.EvidenceWorld.PROVIDER;
import static com.zoop.document.evidence.service.EvidenceWorld.REVISION;
import static com.zoop.document.evidence.service.EvidenceWorld.SUMMARY;
import static com.zoop.document.evidence.service.EvidenceWorld.VERIFIER;
import static com.zoop.document.evidence.service.EvidenceWorld.VERSION;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * The read rules of {@code getEvidence} against in-memory statements, a real grant registry file and a real
 * {@link ArtifactFileStore}. The SQL itself, the transaction and the HTTP shape are proven by the operator smoke against PostgreSQL.
 */
class EvidenceServiceTest {
    @TempDir
    Path temp;

    private static EvidenceResponse get(EvidenceService service, String id) {
        return service.read(id, null, null, null, null, "req-1");
    }

    private static ErrorCode failure(Runnable action) {
        return assertThrows(CustomException.class, action::run).getErrorCode();
    }

    private ErrorCode refused(EvidenceWorld world) {
        return failure(() -> get(world.service(), world.evidenceId));
    }

    // ---- the served shape ------------------------------------------------------------------------------------------------

    @Test
    void servesTheVerifiedQuoteWithCodePointOffsetsAndAnHonestPartialMetadata() throws Exception {
        EvidenceWorld world = new EvidenceWorld(temp).normal();
        int writesBefore = world.registry.writeAttempts();

        EvidenceResponse response = get(world.service(), world.evidenceId);

        assertEquals(world.evidenceId, response.id());
        assertEquals(EvidenceWorld.QUOTE, response.quote());
        assertEquals(5, response.start());
        assertEquals(9, response.end());
        assertEquals(4, response.quote().codePointCount(0, response.quote().length()), "offsets are code points, not UTF-16 units");
        assertEquals(5, response.quote().length());
        assertEquals(ARTICLE, response.articleId());
        assertEquals(VERSION, response.articleVersion());
        assertEquals(VERSION, response.documentVersion());
        assertEquals("제목", response.article().title());
        assertEquals("발행처", response.article().publisher());
        assertEquals(Instant.parse("2026-10-15T00:00:00Z"), response.article().publishedAt());
        assertEquals(Boolean.TRUE, response.quoteVerified());
        assertEquals(List.of(), response.eventIds());
        assertNull(response.sentiment());
        assertNull(response.analysisStatus());
        assertEquals("result-1", response.resultVersion());
        assertEquals("synthetic", response.analysisProvenance().get("sourceKind").stringValue());
        assertEquals(world.evidenceId, response.documentSummary().get("citations").get(0).get("evidenceId").stringValue());
        assertEquals("document-analysis", response.metadata().source());
        assertEquals(EvidenceWorld.NOW, response.metadata().asOf());
        assertNull(response.metadata().graphVersion());
        assertEquals("req-1", response.metadata().requestId());
        assertTrue(response.metadata().partial());
        assertEquals(1, response.metadata().failures().size());
        assertEquals("eventIds", response.metadata().failures().get(0).section());
        assertEquals("SOURCE_UNAVAILABLE", response.metadata().failures().get(0).code());
        assertFalse(response.metadata().failures().get(0).retryable());
        assertNull(response.metadata().failures().get(0).asOf());
        assertEquals(writesBefore, world.registry.writeAttempts(), "the setup wrote the registry; the read must add no write");
    }

    @Test
    void anyPinnedReadIsRefusedBeforeAnythingIsReadAndBlankOrOffsetlessValuesAreInvalid() throws Exception {
        EvidenceWorld world = new EvidenceWorld(temp).normal();
        EvidenceService service = world.service();
        String id = world.evidenceId;

        assertEquals(ErrorCode.VERSION_UNAVAILABLE, failure(() -> service.read(id, "brf-1", null, null, null, "r")));
        assertEquals(0, world.read.calls, "a round must not touch the database");
        assertEquals(ErrorCode.VERSION_UNAVAILABLE, failure(() -> service.read(id, null, "gv-1", null, null, "r")),
                "an S1 citation has no pinned form");
        assertEquals(ErrorCode.VERSION_UNAVAILABLE, failure(() -> service.read(id, null, null, "2026-10-15T00:00:00Z", null, "r")));
        world.read.calls = 0;

        for (String blank : List.of("", " ")) {
            assertEquals(ErrorCode.INVALID_REQUEST, failure(() -> service.read(id, blank, null, null, null, "r")));
            assertEquals(ErrorCode.INVALID_REQUEST, failure(() -> service.read(id, null, blank, null, null, "r")));
            assertEquals(ErrorCode.INVALID_REQUEST, failure(() -> service.read(id, null, null, blank, null, "r")));
            assertEquals(ErrorCode.INVALID_REQUEST, failure(() -> service.read(id, null, null, null, blank, "r")));
        }
        assertEquals(ErrorCode.INVALID_REQUEST, failure(() -> service.read(id, null, null, "2026-10-15T00:00:00", null, "r")));
        assertEquals(ErrorCode.INVALID_REQUEST, failure(() -> service.read(id, null, null, "yesterday", null, "r")));
        assertEquals(ErrorCode.INVALID_REQUEST, failure(() -> service.read(id, "brf-1", null, "yesterday", null, "r")),
                "validation comes before the pin refusal");
        assertEquals(0, world.read.calls);
    }

    @Test
    void anUnknownOrMalformedIdIsNotFoundNotUnavailable() throws Exception {
        EvidenceWorld world = new EvidenceWorld(temp).normal();
        EvidenceService service = world.service();

        assertEquals(ErrorCode.RESOURCE_NOT_FOUND, failure(() -> get(service, "ev-" + "0".repeat(64))));
        for (String malformed : List.of("x", "ev-1", "EV-" + "0".repeat(64), "ev-" + "0".repeat(63) + "G", "ev-" + "0".repeat(65))) {
            assertEquals(ErrorCode.RESOURCE_NOT_FOUND, failure(() -> get(service, malformed)), malformed);
        }
    }

    // ---- company context -------------------------------------------------------------------------------------------------

    @Test
    void aKnownCompanyAddsAFailedSentimentSectionAndNeverASentiment() throws Exception {
        EvidenceWorld world = new EvidenceWorld(temp).normal();
        world.read.companies.add("SYNTH-A");

        EvidenceResponse response = world.service().read(world.evidenceId, null, null, null, "SYNTH-A", "req-2");

        assertNull(response.sentiment());
        assertEquals(List.of("eventIds", "sentiment"), response.metadata().failures().stream().map(f -> f.section()).toList());
        assertTrue(response.metadata().failures().stream().noneMatch(f -> f.retryable()));
        assertNotNull(response.documentSummary(), "the base evidence and summary do not depend on the company");
        assertEquals(ErrorCode.RESOURCE_NOT_FOUND,
                failure(() -> world.service().read(world.evidenceId, null, null, null, "NOPE", "req-3")));
    }

    @Test
    void anUnknownCompanyDoesNotMakeAWithheldEvidenceVisible() throws Exception {
        EvidenceWorld world = new EvidenceWorld(temp).normal();
        world.registry.setAccessStatus(ARTICLE, "private");

        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE,
                failure(() -> world.service().read(world.evidenceId, null, null, null, "NOPE", "r")));
    }

    // ---- structural gate -------------------------------------------------------------------------------------------------

    @Test
    void theCurrentDocumentStateGatesTheEvidence() throws Exception {
        EvidenceWorld world = new EvidenceWorld(temp).normal();
        assertNotNull(get(world.service(), world.evidenceId));

        for (String status : List.of("private", "deleted")) {
            world.registry.setAccessStatus(ARTICLE, status);
            assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(world), status);
        }
        world.registry.setAccessStatus(ARTICLE, "available");
        assertNotNull(get(world.service(), world.evidenceId), "restoring access restores the evidence");

        world.registry.seedArticle(ARTICLE, "news", PROVIDER, null, "available");
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(world), "an unset pointer is no current version");
        world.registry.insertVersionIfAbsent(new com.zoop.document.repository.VersionRow(ARTICLE, "v2", null, null, null, null, null,
                "unknown", null, EvidenceWorld.TEXT, EvidenceWorld.NOW));
        world.registry.movePointer(ARTICLE, null, "v2");
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(world), "a newer current version withholds the old version's evidence");
        world.registry.movePointer(ARTICLE, "v2", VERSION);
        assertNotNull(get(world.service(), world.evidenceId));
    }

    @Test
    void aTextArtifactOtherThanTheVersionsIsWithheld() throws Exception {
        EvidenceWorld world = new EvidenceWorld(temp).normal();
        EvidenceView row = world.read.evidence.get(world.evidenceId);
        world.read.evidence.put(world.evidenceId, new EvidenceView(row.id(), row.articleId(), row.articleVersion(), "text-other",
                row.quote(), row.startOffset(), row.endOffset(), row.inputKind(), row.quoteVerified(), row.verificationArtifactId()));

        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(world));
    }

    @Test
    void onlyVerifiedBodyEvidenceWithConsistentOffsetsIsServed() throws Exception {
        EvidenceWorld world = new EvidenceWorld(temp).normal();
        EvidenceView row = world.read.evidence.get(world.evidenceId);
        List<EvidenceView> broken = List.of(
                new EvidenceView(row.id(), row.articleId(), row.articleVersion(), row.textArtifactId(), row.quote(), row.startOffset(),
                        row.endOffset(), "summary", row.quoteVerified(), row.verificationArtifactId()),
                new EvidenceView(row.id(), row.articleId(), row.articleVersion(), row.textArtifactId(), row.quote(), row.startOffset(),
                        row.endOffset(), row.inputKind(), null, row.verificationArtifactId()),
                new EvidenceView(row.id(), row.articleId(), row.articleVersion(), row.textArtifactId(), row.quote(), row.startOffset(),
                        row.endOffset(), row.inputKind(), Boolean.FALSE, row.verificationArtifactId()),
                new EvidenceView(row.id(), row.articleId(), row.articleVersion(), row.textArtifactId(), row.quote(), row.startOffset(),
                        row.endOffset(), row.inputKind(), row.quoteVerified(), null),
                new EvidenceView(row.id(), row.articleId(), row.articleVersion(), row.textArtifactId(), row.quote(), row.startOffset(),
                        row.endOffset() + 1, row.inputKind(), row.quoteVerified(), row.verificationArtifactId()),
                new EvidenceView(row.id(), row.articleId(), row.articleVersion(), row.textArtifactId(), row.quote(), 4,
                        row.endOffset(), row.inputKind(), row.quoteVerified(), row.verificationArtifactId()));
        for (EvidenceView view : broken) {
            world.read.evidence.put(world.evidenceId, view);
            assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(world), view.toString());
        }
    }

    @Test
    void theOwnerAnalysisMustBeOneAvailableCompanyFreeSummaryOfTheSameDocumentVersion() throws Exception {
        for (int variant = 0; variant < 5; variant++) {
            EvidenceWorld world = new EvidenceWorld(Files.createDirectory(temp.resolve("v" + variant))).normal();
            SummaryView owner = world.read.summaries.get(0);
            world.read.summaries.clear();
            switch (variant) {
                case 0 -> { /* no owner at all */ }
                case 1 -> world.read.summaries.add(new SummaryView(owner.id(), owner.articleId(), owner.articleVersion(), owner.stage(),
                        owner.companyId(), "pending", owner.requestNo(), owner.grantReference(), owner.grantRevision(), owner.aiJobId(),
                        owner.resultVersion(), owner.resultArtifactId(), owner.exactReceiptId(), owner.semanticReceiptId(), owner.resultJson()));
                case 2 -> {
                    world.read.summaries.add(owner);
                    world.read.summaries.add(new SummaryView("an-dup", owner.articleId(), owner.articleVersion(), owner.stage(),
                            owner.companyId(), owner.status(), 2, owner.grantReference(), owner.grantRevision(), "job-dup",
                            owner.resultVersion(), owner.resultArtifactId(), owner.exactReceiptId(), owner.semanticReceiptId(),
                            owner.resultJson()));
                }
                case 3 -> world.read.summaries.add(new SummaryView(owner.id(), owner.articleId(), owner.articleVersion(), "sentiment",
                        "SYNTH-A", owner.status(), owner.requestNo(), owner.grantReference(), owner.grantRevision(), owner.aiJobId(),
                        owner.resultVersion(), owner.resultArtifactId(), owner.exactReceiptId(), owner.semanticReceiptId(), owner.resultJson()));
                default -> world.read.summaries.add(new SummaryView(owner.id(), owner.articleId(), "v-other", owner.stage(),
                        owner.companyId(), owner.status(), owner.requestNo(), owner.grantReference(), owner.grantRevision(), owner.aiJobId(),
                        owner.resultVersion(), owner.resultArtifactId(), owner.exactReceiptId(), owner.semanticReceiptId(), owner.resultJson()));
            }
            assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(world), "variant " + variant);
        }
    }

    // ---- stored result ---------------------------------------------------------------------------------------------------

    @Test
    void aResultThatDoesNotCiteTheEvidenceOrIsNotTheStoredShapeNeverServesAnyBody() throws Exception {
        EvidenceWorld world = new EvidenceWorld(temp).normal();
        SummaryView owner = world.read.summaries.get(0);

        world.read.summaries.set(0, withResult(owner, EvidenceWorld.resultJson("an-1", "artifact-main-1", "result-1",
                n -> ((ObjectNode) n.get("citations").get(0)).put("quote", "다른 인용"))));
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(world), "a citation that disagrees with the evidence row");

        world.read.summaries.set(0, withResult(owner, EvidenceWorld.resultJson("an-1", "artifact-main-1", "result-1",
                n -> ((ObjectNode) n.get("citations").get(0)).put("evidenceId", "ev-" + "1".repeat(64)))));
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(world), "a result that does not cite this evidence");

        for (String broken : new String[] {"{", "[]", "null", "{}"}) {
            world.read.summaries.set(0, withResult(owner, broken));
            assertEquals(ErrorCode.INTERNAL_ERROR, refused(world), broken);
        }
        world.read.summaries.set(0, withResult(owner, null));
        assertEquals(ErrorCode.INTERNAL_ERROR, refused(world));
        world.read.summaries.set(0, withResult(owner, EvidenceWorld.resultJson("an-1", "artifact-main-1", "result-1",
                n -> n.put("extra", "x"))));
        assertEquals(ErrorCode.INTERNAL_ERROR, refused(world), "an unknown key is not served");
        world.read.summaries.set(0, withResult(owner, EvidenceWorld.resultJson("an-1", "artifact-main-1", "result-other", n -> { })));
        assertEquals(ErrorCode.INTERNAL_ERROR, refused(world), "the stored result version must be the row's");
        world.read.summaries.set(0, withResult(owner, EvidenceWorld.resultJson("an-1", "artifact-main-1", "result-1",
                n -> ((ObjectNode) n.get("provenance")).put("sourceKind", 5))));
        assertEquals(ErrorCode.INTERNAL_ERROR, refused(world), "provenance must be the three strings");

        world.read.summaries.set(0, owner);
        assertNotNull(get(world.service(), world.evidenceId));
    }

    private static java.util.function.Consumer<ObjectNode> claim(java.util.function.Consumer<ObjectNode> edit) {
        return result -> {
            ObjectNode claim = com.zoop.common.json.StrictJson.newObject();
            claim.put("claimId", "claim-a");
            claim.put("text", "주장");
            claim.put("assertionKind", "fact");
            claim.putArray("evidenceIds").add("ev-" + "1".repeat(64));
            edit.accept(claim);
            ArrayNode claims = result.putArray("claims");
            claims.add(claim);
        };
    }

    /** Each is a stored result that is NOT the closed {@code AnalysisClaim} shape (4 keys, typed values, enum assertionKind). */
    private static List<java.util.function.Consumer<ObjectNode>> malformedClaims() {
        return List.of(
                claim(c -> c.put("privateDebug", "secret-internal-note")),
                claim(c -> c.putObject("privateDebug").put("nested", "secret-internal-note")),
                claim(c -> c.putObject("text").put("nested", "secret-internal-note")),
                claim(c -> c.put("text", 7)),
                claim(c -> c.put("claimId", 7)),
                claim(c -> c.put("assertionKind", "bogus")),
                claim(c -> c.put("assertionKind", 1)),
                claim(c -> c.putArray("evidenceIds").add(5)),
                claim(c -> c.putArray("evidenceIds").addObject().put("nested", "secret-internal-note")),
                claim(c -> c.put("evidenceIds", "ev-" + "1".repeat(64))),
                claim(c -> c.remove("evidenceIds")),
                claim(c -> c.remove("assertionKind")),
                result -> result.putObject("claims").put("privateDebug", "secret-internal-note"),
                result -> result.put("claims", "secret-internal-note"),
                result -> result.putArray("claims").add("secret-internal-note"),
                result -> result.putArray("claims").add(5),
                result -> result.putArray("claims").addArray().add("secret-internal-note"));
    }

    private static void assertSafeStoredDataFailure(CustomException failure, String label) {
        assertEquals(ErrorCode.INTERNAL_ERROR, failure.getErrorCode(), label);
        assertFalse(String.valueOf(failure.getMessage()).contains("secret-internal-note"), label);
    }

    @Test
    void anOwnerResultWhoseClaimsAreNotTheClosedClaimShapeIsAStoredDataFailureAndLeaksNothing() throws Exception {
        EvidenceWorld world = new EvidenceWorld(temp).normal();
        SummaryView owner = world.read.summaries.get(0);
        int index = 0;
        for (java.util.function.Consumer<ObjectNode> edit : malformedClaims()) {
            world.read.summaries.set(0, withResult(owner,
                    EvidenceWorld.resultJson("an-1", "artifact-main-1", "result-1", edit)));
            assertSafeStoredDataFailure(assertThrows(CustomException.class, () -> get(world.service(), world.evidenceId)),
                    "owner claims variant " + index++);
        }
        world.read.summaries.set(0, withResult(owner, EvidenceWorld.resultJson("an-1", "artifact-main-1", "result-1",
                claim(c -> { }))));
        assertNotNull(get(world.service(), world.evidenceId), "a well-formed claim is still served");
    }

    @Test
    void aDifferentLatestResultWhoseClaimsAreNotTheClosedClaimShapeIsAStoredDataFailureAndLeaksNothing() throws Exception {
        EvidenceWorld world = new EvidenceWorld(temp).normal();
        world.executions("job-3", "an-3", GRANT, REVISION, Set.of("authored-replay"));
        int index = 0;
        for (java.util.function.Consumer<ObjectNode> edit : malformedClaims()) {
            world.read.summaries.removeIf(s -> s.id().equals("an-3"));
            world.read.summaries.add(new SummaryView("an-3", ARTICLE, VERSION, "summary", null, "available", 2, GRANT, REVISION,
                    "job-3", "result-3", "artifact-main-3", "exact-an-3", "artifact-ver-3",
                    EvidenceWorld.resultJson("an-3", "artifact-main-3", "result-3", edit)));
            assertSafeStoredDataFailure(assertThrows(CustomException.class, () -> get(world.service(), world.evidenceId)),
                    "latest claims variant " + index++);
        }
        world.read.summaries.removeIf(s -> s.id().equals("an-3"));
        world.read.summaries.add(new SummaryView("an-3", ARTICLE, VERSION, "summary", null, "available", 2, GRANT, REVISION,
                "job-3", "result-3", "artifact-main-3", "exact-an-3", "artifact-ver-3",
                EvidenceWorld.resultJson("an-3", "artifact-main-3", "result-3", claim(c -> { }))));
        assertEquals("result-3", get(world.service(), world.evidenceId).resultVersion(), "a well-formed latest claim is served");
    }

    private static SummaryView withResult(SummaryView v, String json) {
        return new SummaryView(v.id(), v.articleId(), v.articleVersion(), v.stage(), v.companyId(), v.status(), v.requestNo(),
                v.grantReference(), v.grantRevision(), v.aiJobId(), v.resultVersion(), v.resultArtifactId(), v.exactReceiptId(),
                v.semanticReceiptId(), json);
    }

    // ---- current authority -----------------------------------------------------------------------------------------------

    @Test
    void everyChangeOfTheCurrentGrantWithholdsTheEvidenceAndRestoringItServesAgain() throws Exception {
        EvidenceWorld world = new EvidenceWorld(temp).normal();
        List<String> ops = List.of("read", "store", "model-send", "quote-display");
        List<String> purposes = List.of(SUMMARY, "document-sentiment", VERIFIER);
        List<String> denied = List.of(
                EvidenceWorld.grant(GRANT, REVISION, PROVIDER, false, "known", ops, List.of("authored-replay"), purposes, null),
                EvidenceWorld.grant(GRANT, REVISION, PROVIDER, true, "unknown", ops, List.of("authored-replay"), purposes, null),
                EvidenceWorld.grant(GRANT, REVISION, PROVIDER, true, "denied", ops, List.of("authored-replay"), purposes, null),
                EvidenceWorld.grant(GRANT, "r2", PROVIDER, true, "known", ops, List.of("authored-replay"), purposes, null),
                EvidenceWorld.grant(GRANT, REVISION, "other-source", true, "known", ops, List.of("authored-replay"), purposes, null),
                EvidenceWorld.grant(GRANT, REVISION, PROVIDER, true, "known", ops, List.of("authored-replay"), purposes,
                        "2026-10-15T00:59:59Z"),
                EvidenceWorld.grant(GRANT, REVISION, PROVIDER, true, "known", ops, List.of("authored-replay"), purposes, "not-a-date"),
                EvidenceWorld.grant(GRANT, REVISION, PROVIDER, true, "known", List.of("read", "store", "model-send"),
                        List.of("authored-replay"), purposes, null),
                EvidenceWorld.grant(GRANT, REVISION, PROVIDER, true, "known", ops, List.of("authored-replay"),
                        List.of("document-sentiment", VERIFIER), null),
                EvidenceWorld.grant(GRANT, REVISION, PROVIDER, true, "known", ops, List.of("authored-replay"),
                        List.of(SUMMARY, "document-sentiment"), null),
                EvidenceWorld.grant(GRANT, REVISION, PROVIDER, true, "known", ops, List.of(), purposes, null),
                EvidenceWorld.grant(GRANT, REVISION, PROVIDER, true, "known", ops, List.of("someone-else"), purposes, null),
                EvidenceWorld.grant("other-grant", REVISION, PROVIDER, true, "known", ops, List.of("authored-replay"), purposes, null),
                EvidenceWorld.grant(GRANT, REVISION, "naver-search", true, "known", ops, List.of("authored-replay"), purposes, null));
        for (String grant : denied) {
            world.writeGrants(grant);
            assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(world), grant);
            world.writeGrants(EvidenceWorld.defaultGrant());
            assertNotNull(get(world.service(), world.evidenceId), "the registry is read fresh on every request");
        }
        world.writeGrants(EvidenceWorld.grant(GRANT, REVISION, PROVIDER, true, "known", ops, List.of("authored-replay", "extra"),
                purposes, "2026-10-15T01:00:01Z"));
        assertNotNull(get(world.service(), world.evidenceId), "a wider recipient list and an unexpired grant still cover it");
    }

    @Test
    void theRecipientsTheReceiptsProveAreCheckedAgainstTheCurrentRegistry() throws Exception {
        EvidenceWorld world = new EvidenceWorld(temp).normal();
        world.read.executions.clear();
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(world), "no executions");

        world.read.executions.add(new InMemoryEvidenceRead.Execution("job-1", "an-1", GRANT, REVISION, SUMMARY, Set.of("authored-replay")));
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(world), "the verifier stage has no proven recipient");
        world.read.executions.clear();

        world.executions("job-1", "an-1", GRANT, "r-old", Set.of("authored-replay"));
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(world), "executions under another grant revision prove nothing");
        world.read.executions.clear();

        world.executions("job-1", "an-1", GRANT, REVISION, Set.of("openai-compatible:r1"));
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(world), "a recipient the registry does not list");
        world.read.executions.clear();

        world.executions("job-1", "an-1", GRANT, REVISION, Set.of());
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(world), "an empty recipient set is no authorization");
    }

    @Test
    void generationAndVerificationRecipientsAreBothRequiredAndNeitherStandsInForTheOther() throws Exception {
        EvidenceWorld world = new EvidenceWorld(temp).normal();
        world.read.executions.clear();
        world.read.executions.add(new InMemoryEvidenceRead.Execution("job-1", "an-1", GRANT, REVISION, SUMMARY, Set.of("openai-compatible:r1")));
        world.read.executions.add(new InMemoryEvidenceRead.Execution("job-1", "an-1", GRANT, REVISION, VERIFIER, Set.of("typesafe-native:r2")));
        List<String> operations = List.of("read", "store", "model-send", "quote-display");
        List<String> allPurposes = List.of(SUMMARY, "document-sentiment", VERIFIER);

        world.writeGrants(EvidenceWorld.grant(GRANT, REVISION, PROVIDER, true, "known", operations, List.of("openai-compatible:r1"), allPurposes, null));
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(world), "the generation recipient does not authorize the verifier");
        world.writeGrants(EvidenceWorld.grant(GRANT, REVISION, PROVIDER, true, "known", operations, List.of("typesafe-native:r2"), allPurposes, null));
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(world), "the verifier recipient does not authorize the generator");
        world.writeGrants(EvidenceWorld.grant(GRANT, REVISION, PROVIDER, true, "known", operations,
                List.of("openai-compatible:r1", "typesafe-native:r2"), allPurposes, null));
        assertNotNull(get(world.service(), world.evidenceId), "both proven recipients granted");
    }

    @Test
    void anUnsetOrUnusableRegistryIsUnavailableNeverOpenAndNeverEmpty() throws Exception {
        EvidenceWorld world = new EvidenceWorld(temp).normal();

        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, failure(() -> get(world.service(null, world.store), world.evidenceId)));
        assertTrue(world.read.calls <= 1, "without a registry nothing beyond the evidence row is read");
        Files.writeString(world.grants, "{");
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, refused(world));
        Files.writeString(world.grants, "{\"schemaVersion\":\"other\",\"grants\":[]}");
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, refused(world));
        Files.delete(world.grants);
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, refused(world));
        Files.write(world.grants, new byte[1_000_001]);
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, refused(world));
        world.writeGrants(EvidenceWorld.defaultGrant());
        assertNotNull(get(world.service(), world.evidenceId));
    }

    @Test
    void aDatabaseFailureIsUnavailableNeverABlankSuccess() throws Exception {
        EvidenceWorld world = new EvidenceWorld(temp).normal();

        world.read.failure = new QueryTimeoutException("canceling statement due to statement timeout");
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, refused(world));

        world.read.failure = null;
        EvidenceService failingTransaction = new EvidenceService(world.read, world.registry, new DocumentReadGrants(world.grants),
                new DocumentReadSources(null), (version, asOf, evidenceId) -> null, new EvidenceArtifactReader(null),
                java.time.Clock.fixed(EvidenceWorld.NOW, java.time.ZoneOffset.UTC),
                new TransactionOperations() {
                    @Override
                    public <T> T execute(org.springframework.transaction.support.TransactionCallback<T> action) {
                        throw new CannotCreateTransactionException("no connection");
                    }
                });
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, failure(() -> get(failingTransaction, world.evidenceId)));
    }

    // ---- latest summary --------------------------------------------------------------------------------------------------

    @Test
    void theSummaryIsTheLatestRequestsAndNeverAnOlderAvailableOne() throws Exception {
        EvidenceWorld world = new EvidenceWorld(temp).normal();

        world.read.summaries.add(new SummaryView("an-3", ARTICLE, VERSION, "summary", null, "pending", 2, GRANT, REVISION, "job-3",
                null, null, null, null, null));
        EvidenceResponse pending = get(world.service(), world.evidenceId);
        assertEquals(world.evidenceId, pending.id(), "the stored evidence stays servable");
        assertNull(pending.documentSummary());
        assertNull(pending.resultVersion());
        assertNull(pending.analysisProvenance());

        world.read.summaries.set(1, new SummaryView("an-3", ARTICLE, VERSION, "summary", null, "withheld", 2, GRANT, REVISION, "job-3",
                null, null, null, null, null));
        assertNull(get(world.service(), world.evidenceId).documentSummary());
        world.read.summaries.set(1, new SummaryView("an-3", ARTICLE, VERSION, "summary", null, "failed", 2, GRANT, REVISION, "job-3",
                null, null, null, null, null));
        assertNull(get(world.service(), world.evidenceId).documentSummary());

        String newerEvidence = EvidenceWorld.evidenceIdOf("an-3");
        world.read.summaries.set(1, new SummaryView("an-3", ARTICLE, VERSION, "summary", null, "available", 2, GRANT, REVISION, "job-3",
                "result-3", "artifact-main-3", "exact-an-3", "artifact-ver-3",
                EvidenceWorld.resultJson("an-3", "artifact-main-3", "result-3", n -> { })));
        assertNull(get(world.service(), world.evidenceId).documentSummary(), "a newer result without proven calls is withheld");

        world.executions("job-3", "an-3", GRANT, REVISION, Set.of("authored-replay"));
        EvidenceResponse newer = get(world.service(), world.evidenceId);
        assertEquals("result-3", newer.resultVersion());
        assertEquals(newerEvidence, newer.documentSummary().get("citations").get(0).get("evidenceId").stringValue());
        assertEquals(world.evidenceId, newer.id(), "the old evidence is still the evidence that was asked for");

        world.writeGrants(EvidenceWorld.grant(GRANT, "r2", PROVIDER, true, "known", List.of("read", "store", "model-send", "quote-display"),
                List.of("authored-replay"), List.of(SUMMARY, VERIFIER), null));
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(world));
    }

    @Test
    void aLatestResultThatIsNotTheStoredShapeIsAStoredDataFailure() throws Exception {
        EvidenceWorld world = new EvidenceWorld(temp).normal();
        world.read.summaries.add(new SummaryView("an-3", ARTICLE, VERSION, "summary", null, "available", 2, GRANT, REVISION, "job-3",
                "result-3", "artifact-main-3", "exact-an-3", "artifact-ver-3", "{\"schemaVersion\":\"zoop-ai-s1-1\"}"));

        assertEquals(ErrorCode.INTERNAL_ERROR, refused(world));
    }

    // ---- a summary served from the artifact cache --------------------------------------------------------------------------

    @Test
    void aCacheServedSummaryIsServedUnderTheCreatorsProvenRecipients() throws Exception {
        EvidenceWorld world = new EvidenceWorld(temp).cached();

        int writes = world.registry.writeAttempts();

        EvidenceResponse response = get(world.service(), world.evidenceId);

        assertEquals("result-2", response.resultVersion());
        assertEquals(world.evidenceId, response.documentSummary().get("citations").get(0).get("evidenceId").stringValue());
        assertEquals(writes, world.registry.writeAttempts(), "the read wrote nothing");
    }

    @Test
    void theCacheProofReadsOnlyAndWorksWhileAnOperatorHoldsTheStoreLock() throws Exception {
        EvidenceWorld world = new EvidenceWorld(temp).cached();
        Files.delete(world.root.resolve(ArtifactFileStore.LOCK_FILE));
        int writes = world.registry.writeAttempts();
        List<String> before = snapshot(world.root);

        assertNotNull(get(world.service(), world.evidenceId));
        assertFalse(Files.exists(world.root.resolve(ArtifactFileStore.LOCK_FILE)), "the read creates no lock file");
        assertEquals(before, snapshot(world.root), "no file, directory, temporary file or permission changed");
        assertEquals(writes, world.registry.writeAttempts());

        try (ArtifactFileStore.Session operator = world.store.open()) {
            assertNotNull(get(world.service(), world.evidenceId), "an operator run does not block the read");
            assertNotNull(operator);
        }
    }

    @Test
    void aMissingRootOrAnUnreadableReceiptIsUnavailableAndAMismatchingOneIsWithheld() throws Exception {
        EvidenceWorld world = new EvidenceWorld(temp).cached();
        Path receipt = world.root.resolve("exact_receipt").resolve("exact-an-2.json");

        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, failure(() -> get(world.service(world.grants, null), world.evidenceId)),
                "without an artifact root only this read cannot be answered");
        Files.setPosixFilePermissions(receipt, PosixFilePermissions.fromString("rw-r--r--"));
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, refused(world), "an insecure file is a storage problem, not 'no evidence'");
        Files.setPosixFilePermissions(receipt, PosixFilePermissions.fromString("rw-------"));
        assertNotNull(get(world.service(), world.evidenceId));

        byte[] original = Files.readAllBytes(receipt);
        Files.write(receipt, EvidenceWorld.bytes("{}"));
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(world), "a file that disagrees with the registry's hash");
        Files.write(receipt, original);
        Path moved = Files.move(receipt, world.directory.resolve("moved.json"));
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(world), "a missing file");
        Files.move(moved, receipt);
        assertNotNull(get(world.service(), world.evidenceId));
    }

    @Test
    void theNormalPathNeedsNoArtifactRoot() throws Exception {
        EvidenceWorld world = new EvidenceWorld(temp).normal();

        assertNotNull(get(world.service(world.grants, null), world.evidenceId));
    }

    @Test
    void aReceiptThatDoesNotProveExactlyThisAnalysisIsNeverAccepted() throws Exception {
        List<java.util.function.Consumer<ObjectNode>> edits = new ArrayList<>();
        edits.add(n -> n.put("schemaVersion", "zoop-exact-receipt-2"));
        edits.add(n -> n.put("analysisId", "an-9"));
        edits.add(n -> n.put("aiJobId", "job-9"));
        edits.add(n -> n.put("kind", "document-sentiment"));
        edits.add(n -> n.put("documentId", "art-9"));
        edits.add(n -> n.put("documentVersion", "v9"));
        edits.add(n -> n.put("textArtifactId", "text-9"));
        edits.add(n -> n.put("textSha256", "c".repeat(64)));
        edits.add(n -> n.put("resultVersion", "result-9"));
        edits.add(n -> n.put("policyVersion", "zoop-document-gate-1"));
        edits.add(n -> n.put("creatorJobId", "job-2"));
        edits.add(n -> n.put("creatorJobId", ""));
        edits.add(n -> n.put("creatorJobId", "job-x"));
        edits.add(n -> n.put("inputDigest", "d".repeat(64)));
        edits.add(n -> n.put("inputDigest", "short"));
        edits.add(n -> n.put("extra", "x"));
        edits.add(n -> n.remove("citations"));
        edits.add(n -> n.putArray("citations"));
        edits.add(n -> ((ObjectNode) n.get("citations").get(0)).put("evidenceId", "ev-" + "2".repeat(64)));
        edits.add(n -> ((ObjectNode) n.get("citations").get(0)).put("modelEvidenceId", "e2"));
        edits.add(n -> ((ObjectNode) n.get("citations").get(0)).put("start", 6));
        edits.add(n -> ((ObjectNode) n.get("citations").get(0)).put("end", 10));
        edits.add(n -> ((ObjectNode) n.get("citations").get(0)).put("extra", 1));
        for (int i = 0; i < edits.size(); i++) {
            Path dir = Files.createDirectory(temp.resolve("w" + i));
            EvidenceWorld world = new EvidenceWorld(dir).cached(edits.get(i));
            assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(world), "receipt edit " + i);
        }
    }

    @Test
    void theArtifactIdsInSqlMustDeriveFromTheReceiptsCreatorJob() throws Exception {
        EvidenceWorld world = new EvidenceWorld(temp).cached();
        SummaryView cached = world.read.summaries.get(1);

        world.read.summaries.set(1, new SummaryView(cached.id(), cached.articleId(), cached.articleVersion(), cached.stage(), null,
                cached.status(), cached.requestNo(), cached.grantReference(), cached.grantRevision(), cached.aiJobId(),
                cached.resultVersion(), EvidenceWorld.artifactId("job-other", SUMMARY), cached.exactReceiptId(),
                cached.semanticReceiptId(), cached.resultJson()));
        assertEquals(ErrorCode.INTERNAL_ERROR, refused(world), "the stored result names an artifact that is not the row's");

        world.read.summaries.set(1, new SummaryView(cached.id(), cached.articleId(), cached.articleVersion(), cached.stage(), null,
                cached.status(), cached.requestNo(), cached.grantReference(), cached.grantRevision(), cached.aiJobId(),
                cached.resultVersion(), cached.resultArtifactId(), cached.exactReceiptId(),
                EvidenceWorld.artifactId("job-other", VERIFIER), cached.resultJson()));
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(world), "the verifier artifact is not the creator's");
    }

    @Test
    void theCreatorMustBeAnotherSummaryOfTheSameDocumentVersionWithItsOwnProvenCalls() throws Exception {
        EvidenceWorld world = new EvidenceWorld(temp).cached();

        world.read.identities.set(0, new com.zoop.document.evidence.repository.AnalysisIdentity("an-2", ARTICLE, VERSION, "summary", null));
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(world), "the creator cannot be the analysis itself");
        for (var identity : List.of(
                new com.zoop.document.evidence.repository.AnalysisIdentity("an-0", "art-9", VERSION, "summary", null),
                new com.zoop.document.evidence.repository.AnalysisIdentity("an-0", ARTICLE, "v9", "summary", null),
                new com.zoop.document.evidence.repository.AnalysisIdentity("an-0", ARTICLE, VERSION, "sentiment", "SYNTH-A"))) {
            world.read.identities.set(0, identity);
            assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(world), identity.toString());
        }
        world.read.identities.clear();
        world.read.jobs.clear();
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(world), "an unknown creator job");
    }

    @Test
    void theCreatorsExecutionsMustBeUnderTheSameGrantSnapshotAndRegistryRecipients() throws Exception {
        EvidenceWorld world = new EvidenceWorld(temp).cached();
        world.read.executions.clear();
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(world), "no creator executions");

        world.executions("job-0", "an-0", GRANT, "r-old", Set.of("authored-replay"));
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(world), "another grant revision");
        world.read.executions.clear();
        world.executions("job-0", "an-9", GRANT, REVISION, Set.of("authored-replay"));
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(world), "executions owned by another analysis");
        world.read.executions.clear();
        world.executions("job-0", "an-0", GRANT, REVISION, Set.of("openai-compatible:r1"));
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(world), "a recipient the current registry does not list");
        world.read.executions.clear();
        world.executions("job-0", "an-0", GRANT, REVISION, Set.of("authored-replay"));
        assertNotNull(get(world.service(), world.evidenceId));

        world.writeGrants(EvidenceWorld.grant(GRANT, REVISION, PROVIDER, true, "known", List.of("read", "store", "model-send", "quote-display"),
                List.of("someone-else"), List.of(SUMMARY, VERIFIER), null));
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, refused(world), "recipient removed from the current registry");
    }

    @Test
    void aCacheServedLatestSummaryGoesThroughTheSameProof() throws Exception {
        EvidenceWorld world = new EvidenceWorld(temp).normal();
        // an-2 was served from the cache of creator job-0; the evidence being read belongs to an-1
        String main = EvidenceWorld.artifactId("job-0", SUMMARY);
        String verifier = EvidenceWorld.artifactId("job-0", VERIFIER);
        world.read.summaries.add(new SummaryView("an-0", ARTICLE, VERSION, "summary", null, "withheld", 2, GRANT, REVISION, "job-0",
                null, null, null, null, null));
        world.read.addIdentity("job-0", new com.zoop.document.evidence.repository.AnalysisIdentity("an-0", ARTICLE, VERSION, "summary", null));
        world.read.summaries.add(world.summary("an-2", "job-2", 3, "available", "exact-an-2", "result-2", main, verifier,
                EvidenceWorld.resultJson("an-2", main, "result-2", n -> { })));
        world.executions("job-0", "an-0", GRANT, REVISION, Set.of("authored-replay"));
        world.writeReceipt("exact-an-2", world.receipt("an-2", "job-2", "job-0", "result-2", n -> { }));

        assertEquals("result-2", get(world.service(), world.evidenceId).resultVersion());
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, failure(() -> get(world.service(world.grants, null), world.evidenceId)),
                "the latest summary needs the receipt file and no root is configured");

        Files.write(world.root.resolve("exact_receipt").resolve("exact-an-2.json"), EvidenceWorld.bytes("{}"));
        EvidenceResponse withheld = get(world.service(), world.evidenceId);
        assertNull(withheld.documentSummary(), "a latest summary whose receipt does not match is withheld, not served");
        assertEquals(world.evidenceId, withheld.id());
    }

    private static List<String> snapshot(Path root) throws IOException {
        try (Stream<Path> paths = Files.walk(root)) {
            List<String> entries = new ArrayList<>();
            for (Path path : paths.sorted().toList()) {
                entries.add(root.relativize(path) + "|" + Files.getPosixFilePermissions(path, LinkOption.NOFOLLOW_LINKS) + "|"
                        + Files.getLastModifiedTime(path, LinkOption.NOFOLLOW_LINKS) + "|"
                        + (Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS) ? Files.size(path) : -1));
            }
            return entries;
        }
    }
    @Test
    void legacyBriefingCitationIdsAreAcceptedOnlyThroughTheRoundBoundReader() throws Exception {
        EvidenceWorld world = new EvidenceWorld(temp);
        String savedId = "evidence-grouped-94b3ffb5802ce7c7eae029378b56";
        var port = new com.zoop.document.evidence.graph.GraphEvidenceReader() {
            public com.zoop.document.evidence.graph.GraphEvidence read(String version, Instant at, String id) {
                throw new AssertionError("a round must not be dropped");
            }
            public RoundRead readRound(String round, String version, Instant at, String id, String company, String request) {
                if (!savedId.equals(id)) throw new CustomException(ErrorCode.EVIDENCE_UNAVAILABLE);
                assertEquals("saved-round", round);
                var facts = new com.zoop.document.evidence.graph.GraphEvidence("reconstructed", EvidenceWorld.NOW, null, List.of(), List.of(), List.of());
                var response = new com.zoop.document.evidence.dto.EvidenceResponse(id, "saved quote", 0, 11, "article", "v1",
                        null, true, List.of("issue"), null, null, "v1", null, null, null, null);
                return new RoundRead(facts, response);
            }
        };
        var service = world.service(null, null, world.store, port);
        assertEquals("saved quote", service.read(savedId, "saved-round", null, null, null, "r").quote());
        assertEquals(ErrorCode.RESOURCE_NOT_FOUND, failure(() -> service.read(savedId, null, null, null, null, "r")));
        assertEquals(ErrorCode.EVIDENCE_UNAVAILABLE, failure(() -> service.read("not-in-round", "saved-round", null, null, null, "r")));
        assertEquals(0, world.read.calls, "round membership and its preserved source own the legacy read");
    }

}
