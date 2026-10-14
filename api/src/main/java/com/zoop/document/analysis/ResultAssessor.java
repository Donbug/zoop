package com.zoop.document.analysis;

import java.time.DateTimeException;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import java.util.stream.Collectors;

import com.zoop.ai.AnalysisJobStatus;
import com.zoop.ai.AnalysisKind;
import com.zoop.ai.AnalysisResult;
import com.zoop.ai.ExecutionMode;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import com.zoop.common.json.Text;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

/**
 * Decides what an AI result is worth to this app. It is pure: the result, the stored submit, the stored document text, the
 * current grant registry and the clock go in, an {@link Assessment} (or a refusal to write anything) comes out.
 *
 * <p>Two kinds of "no":
 * <ul>
 *   <li><b>Integrity</b> ({@link AnalysisException}, nothing is written, the analysis stays pending): the delivered result is
 *       not the answer to this analysis (its echoed input differs, the artifacts belong to an unknown job, the receipts
 *       disagree). The operator investigates; the app never settles a result it cannot attribute.</li>
 *   <li><b>Withheld</b> (terminal, stored with a reason): the result is attributable, but a rights or verification gate blocks
 *       its use: the service withheld delivery, the app's own current-grant check denies it, the verifier did not support
 *       it, a content gate (digests, policy, quotes, claims) fails, or the article is no longer available.</li>
 * </ul>
 * Nothing the AI service says about itself is trusted: artifact ids, result versions and model-configuration revisions are
 * recomputed with Python-parity canonical JSON, the verification outcome is recomputed from the verifier's own verdicts, and
 * every citation is checked against the stored text at Unicode code point offsets.
 */
final class ResultAssessor {
    /** The document gate policy the worker stamps on its artifacts ({@code POLICY_VERSION} of {@code zoop_ai.contracts}). */
    static final String POLICY_VERSION = "zoop-document-gate-2";
    static final String SCHEMA = "zoop-ai-s1-1";
    static final String EXACT_SCHEMA = "zoop-exact-receipt-1";
    static final String CACHE_HIT = "artifact.cache_hit";
    private static final Set<String> LABELS = Set.of("positive", "negative", "mixed", "undetermined");

    /** The analysis whose {@code ai_job_id} created a set of artifacts (the creator of a cache-served result). */
    record Creator(String analysisId, String submitIdentity) {
    }

    interface Creators {
        Optional<Creator> byAiJobId(String aiJobId);
    }

    record Input(String analysisId, String aiJobId, AnalysisSubmit submit, AnalysisResult result, String textSha256,
            Creators creators, GrantRegistry registry, Instant now, boolean articleAvailable) {
    }

    /** Which job's attempts a result's receipts are, and the analysis that owns that job. */
    record ReceiptScope(String creatorJobId, String ownerAnalysisId) {
    }

    record EvidenceSeed(String id, AiPayload.Citation citation) {
    }

    /** Everything an {@code available} settlement stores. */
    record Content(AiPayload.Artifact main, AiPayload.Artifact verifier, String resultVersion, Instant producedAt,
            String resultJson, List<EvidenceSeed> evidence, String exactReceiptId, byte[] exactReceipt,
            AnalysisResult.Receipt generation, List<String> recipients) {
    }

    sealed interface Assessment permits Available, Withheld {
    }

    record Available(ReceiptScope scope, Content content) implements Assessment {
    }

    /** {@code scope} is null when the receipts belong to an unknown creator (a cache-served, service-withheld result). */
    record Withheld(String reason, ReceiptScope scope) implements Assessment {
    }

    /** Receipts of this analysis must be about its own two stages, finished, and have unique attempt ids. */
    static void requireReceipts(AnalysisSubmit submit, List<AnalysisResult.Receipt> receipts) {
        Set<String> attempts = new HashSet<>();
        for (AnalysisResult.Receipt receipt : receipts) {
            boolean stage = receipt.stage() == submit.kind() || receipt.stage() == AnalysisKind.SEMANTIC_VERIFICATION;
            boolean finished = receipt.state() != AnalysisResult.Receipt.CallState.STARTED
                    && receipt.state() != AnalysisResult.Receipt.CallState.UNKNOWN;
            if (!stage || !finished || !attempts.add(receipt.attemptId())) {
                throw integrity(AnalysisFailure.RECEIPTS_INVALID, "receipt");
            }
        }
    }

    Assessment assess(Input in) {
        try {
            return assessChecked(in);
        } catch (StrictJson.Malformed malformed) {
            throw integrity(AnalysisFailure.RESULT_PAYLOAD_INVALID, "shape");
        }
    }

    private Assessment assessChecked(Input in) {
        AnalysisSubmit submit = in.submit();
        AnalysisJobStatus status = in.result().status();
        List<AnalysisResult.Receipt> receipts = in.result().receipts();
        requireReceipts(submit, receipts);
        boolean cacheHit = CACHE_HIT.equals(status.phase());
        ReceiptScope own = new ReceiptScope(in.aiJobId(), in.analysisId());

        if (in.result().delivery().state() == AnalysisResult.Delivery.State.WITHHELD) {
            // No payload: the creator of a cache-served result is unknown, so its receipts are not recorded here.
            return new Withheld(in.result().delivery().reason().orElse("withheld"), cacheHit ? null : own);
        }
        AiPayload payload = AiPayload.parse(in.result().readyPayload()
                .orElseThrow(() -> integrity(AnalysisFailure.RESULT_BINDING_INVALID, "payload_absent")).untrustedJson());

        // B1: this payload is the ready job that was asked about.
        if (!SCHEMA.equals(payload.schemaVersion()) || !in.aiJobId().equals(payload.jobId()) || !"ready".equals(payload.state())
                || !payload.inputDigest().equals(status.inputDigest()) || !payload.phase().equals(status.phase())) {
            throw integrity(AnalysisFailure.RESULT_BINDING_INVALID, "payload");
        }
        // B2: and it was computed from exactly the stored submit.
        if (!Canonical.write(payload.input()).equals(submit.canonicalText())) {
            throw integrity(AnalysisFailure.RESULT_BINDING_INVALID, "input_changed");
        }
        // B3: artifact ids are unique, match what the status announced, and come from one job.
        Set<String> artifactIds = new HashSet<>();
        Set<String> jobs = new HashSet<>();
        for (AiPayload.Artifact artifact : payload.artifacts()) {
            if (!artifactIds.add(artifact.artifactId())) {
                throw integrity(AnalysisFailure.RESULT_BINDING_INVALID, "artifact_ids");
            }
            jobs.add(artifact.jobId());
        }
        if (payload.artifactIds().size() != artifactIds.size() || !new HashSet<>(payload.artifactIds()).equals(artifactIds)
                || status.artifactIds().size() != artifactIds.size() || !new HashSet<>(status.artifactIds()).equals(artifactIds)
                || jobs.size() > 1) {
            throw integrity(AnalysisFailure.RESULT_BINDING_INVALID, "artifact_ids");
        }
        String creatorJob = jobs.isEmpty() ? in.aiJobId() : jobs.iterator().next();
        ReceiptScope scope;
        if (cacheHit) {
            // The artifacts and calls are those of the job that created them: it must be an analysis of this app that asked
            // the very same question.
            Set<String> artifactAttempts = payload.artifacts().stream().map(AiPayload.Artifact::attemptId).collect(Collectors.toSet());
            Set<String> callAttempts = receipts.stream().map(AnalysisResult.Receipt::attemptId).collect(Collectors.toSet());
            if (!artifactAttempts.equals(callAttempts)) {
                throw integrity(AnalysisFailure.RESULT_BINDING_INVALID, "cached_receipts");
            }
            Creator creator = in.creators().byAiJobId(creatorJob)
                    .orElseThrow(() -> integrity(AnalysisFailure.ARTIFACT_CREATOR_UNKNOWN, "job"));
            if (!creator.submitIdentity().equals(submit.identity())) {
                throw integrity(AnalysisFailure.ARTIFACT_CREATOR_UNKNOWN, "input");
            }
            scope = new ReceiptScope(creatorJob, creator.analysisId());
        } else {
            if (!creatorJob.equals(in.aiJobId())) {
                throw integrity(AnalysisFailure.RESULT_BINDING_INVALID, "artifact_job");
            }
            scope = own;
        }
        // B4: the typed receipts the service reported are exactly the calls the payload carries.
        if (receipts.size() != payload.calls().size() || !payload.calls().containsAll(receipts)) {
            throw integrity(AnalysisFailure.RECEIPTS_INVALID, "calls");
        }

        // G1: one generation artifact, one independent verifier, and the first depends on the second.
        List<AiPayload.Artifact> mains = payload.artifacts().stream().filter(a -> a.kind() == submit.kind()).toList();
        List<AiPayload.Artifact> verifiers = payload.artifacts().stream()
                .filter(a -> a.kind() == AnalysisKind.SEMANTIC_VERIFICATION).toList();
        if (payload.artifacts().size() != 2 || mains.size() != 1 || verifiers.size() != 1) {
            return new Withheld("artifact_set_invalid", scope);
        }
        AiPayload.Artifact main = mains.get(0);
        AiPayload.Artifact verifier = verifiers.get(0);
        if (!main.dependencyRefs().equals(List.of(verifier.artifactId())) || !verifier.dependencyRefs().isEmpty()) {
            return new Withheld("semantic_receipt_missing", scope);
        }
        String gate = contentGate(in, payload, main, verifier, receipts, creatorJob);
        if (gate != null) {
            return new Withheld(gate, scope);
        }
        // Rights, then verification, then the article: the first that denies is the recorded reason.
        List<String> recipients = recipients(submit, receipts);
        if (recipients == null) {
            return new Withheld("recipient_unproven", scope);
        }
        FlatGrant grant = in.registry().current(submit.grantId()).orElse(null);
        String denial = GrantRegistry.evaluate(grant, submit.sourceId(), submit.grantRevision(),
                GrantRegistry.purposesOf(submit.kind().wire()), recipients, true, in.now());
        if (denial != null) {
            return new Withheld(denial, scope);
        }
        String semantic = semantic(verifier.verification());
        if (!"supported".equals(semantic)) {
            return new Withheld("semantic_" + semantic, scope);
        }
        if (!in.articleAvailable()) {
            return new Withheld("article_access_unavailable", scope);
        }
        Instant producedAt = producedAt(main.producedAt());
        if (producedAt == null) {
            return new Withheld("artifact_timestamp_invalid", scope);
        }
        AnalysisResult.Receipt generation = receipts.stream().filter(r -> r.attemptId().equals(main.attemptId())).findFirst().get();
        return content(in, scope, main, verifier, producedAt, generation, creatorJob, recipients);
    }

    /** G2 to G6 of the settlement design; returns the withheld reason of the first gate that fails, or null. */
    private static String contentGate(Input in, AiPayload payload, AiPayload.Artifact main, AiPayload.Artifact verifier,
            List<AnalysisResult.Receipt> receipts, String creatorJob) {
        AnalysisSubmit submit = in.submit();
        List<AiPayload.Artifact> both = List.of(main, verifier);
        for (AiPayload.Artifact artifact : both) {
            if (!POLICY_VERSION.equals(artifact.policyVersion())) {
                return "document_policy_outdated";
            }
        }
        String document = Canonical.write(submit.documentNode());
        String provenance = Canonical.write(submit.provenanceNode());
        for (AiPayload.Artifact artifact : both) {
            if (!SCHEMA.equals(artifact.schemaVersion()) || !artifact.inputDigest().equals(payload.inputDigest())
                    || !artifact.jobId().equals(creatorJob) || artifact.sourceRefs().size() != 1
                    || !Canonical.write(artifact.sourceRefs().get(0)).equals(document)
                    || !Canonical.write(artifact.provenance()).equals(provenance)
                    || !submit.companyId().equals(artifact.companyId()) || !submit.grantId().equals(artifact.grantId())
                    || !submit.grantRevision().equals(artifact.grantRevision())) {
                return "artifact_context_mismatch";
            }
        }
        // G4: the validated call of each artifact, for its stage, in this mode, under the pinned policy.
        AnalysisResult.Receipt mainCall = call(receipts, main.attemptId());
        if (!callMatches(mainCall, main, submit)) {
            return "artifact_receipt_missing";
        }
        AnalysisResult.Receipt verifierCall = call(receipts, verifier.attemptId());
        if (!callMatches(verifierCall, verifier, submit)) {
            return "semantic_receipt_invalid";
        }
        // G3: identities the app recomputes instead of trusting.
        for (AiPayload.Artifact artifact : both) {
            AnalysisResult.Receipt call = artifact == main ? mainCall : verifierCall;
            ObjectNode identity = StrictJson.newObject();
            identity.put("jobId", artifact.jobId());
            identity.put("kind", artifact.kind().wire());
            identity.put("inputDigest", artifact.inputDigest());
            ObjectNode version = StrictJson.newObject();
            version.put("inputDigest", artifact.inputDigest());
            version.put("kind", artifact.kind().wire());
            version.set("result", artifact.resultNode());
            if (!artifact.artifactId().equals("artifact-" + Canonical.digest(identity))
                    || !artifact.resultVersion().equals("result-" + Canonical.digest(version))
                    || !artifact.modelConfigRevision().equals(Canonical.digest(ReceiptRecords.configNode(call)))) {
                return "artifact_digest_mismatch";
            }
        }
        // G5: exactness and the semantic verdict, recomputed from the verifier's own verdicts.
        AiPayload.Answer answer = main.answer();
        AiPayload.Verification verification = verifier.verification();
        if (answer == null || verification == null || answer.claims().isEmpty() || answer.citations().isEmpty()
                || verification.verdicts().isEmpty() || (submit.kind() == AnalysisKind.DOCUMENT_SENTIMENT
                && !LABELS.contains(answer.label()))) {
            return "artifact_validation_invalid";
        }
        String semantic = semantic(verification);
        boolean supported = "supported".equals(semantic);
        if (!main.validation().exact() || !verifier.validation().exact() || main.validation().eligible() != supported
                || verifier.validation().eligible() != supported || !semantic.equals(main.validation().semantic())
                || !semantic.equals(verifier.validation().semantic())) {
            return "artifact_validation_invalid";
        }
        Set<String> known = answer.claims().stream().map(AiPayload.Claim::claimId).collect(Collectors.toSet());
        List<String> returned = verification.verdicts().stream().map(AiPayload.Verdict::claimId).toList();
        if (!Canonical.write(verifier.claimsNode()).equals(Canonical.write(main.claimsNode()))
                || !new HashSet<>(returned).equals(known) || returned.size() != known.size()
                || !Canonical.write(main.claimsNode()).equals(Canonical.write(main.resultNode().get("claims")))) {
            return "semantic_claim_coverage_invalid";
        }
        return exactGate(submit, answer);
    }

    /** G6: the contract's own exact check ({@code zoop_ai.contracts.exact}) against the stored document text. */
    private static String exactGate(AnalysisSubmit submit, AiPayload.Answer answer) {
        Set<String> evidenceIds = new HashSet<>();
        for (AiPayload.Citation citation : answer.citations()) {
            if (!evidenceIds.add(citation.evidenceId())) {
                return "duplicate_reference";
            }
        }
        Set<String> claimIds = answer.claims().stream().map(AiPayload.Claim::claimId).collect(Collectors.toSet());
        if (claimIds.size() != answer.claims().size()) {
            return "duplicate_reference";
        }
        for (AiPayload.Citation citation : answer.citations()) {
            String slice = Text.codePointSlice(submit.text(), citation.start(), citation.end());
            if (!citation.documentId().equals(submit.documentId()) || !citation.documentVersion().equals(submit.documentVersion())
                    || !citation.textArtifactId().equals(submit.textArtifactId()) || !"body".equals(citation.inputKind())
                    || !"unicode_code_point".equals(citation.offsetUnit()) || slice == null
                    || !slice.equals(citation.quote())) {
                return "quote_mismatch";
            }
            boolean located = !citation.rawLocatorIds().isEmpty();
            boolean covered = false;
            for (String id : citation.rawLocatorIds()) {
                AnalysisSubmit.RawLocator locator = submit.locators().stream().filter(l -> l.id().equals(id)).findFirst().orElse(null);
                if (locator == null) {
                    located = false;
                } else if (locator.start() <= citation.start() && citation.end() <= locator.end()) {
                    covered = true;
                }
            }
            if (!located || !covered) {
                return "raw_locator_mismatch";
            }
        }
        List<String> limitations = new ArrayList<>();
        List<String> rendered = new ArrayList<>();
        for (AiPayload.Claim claim : answer.claims()) {
            boolean limitation = "limitation".equals(claim.assertionKind());
            if (!"fact".equals(claim.assertionKind()) && !"interpretation".equals(claim.assertionKind()) && !limitation) {
                return "artifact_validation_invalid";
            }
            if (!evidenceIds.containsAll(claim.evidenceIds()) || (!limitation && claim.evidenceIds().isEmpty())) {
                return "claim_citation_missing";
            }
            if (limitation) {
                limitations.add(claim.text());
            } else {
                rendered.add(claim.text());
            }
        }
        if (!answer.limitations().equals(limitations)) {
            return "limitation_claim_coverage_invalid";
        }
        if (!answer.text().equals(String.join("\n", rendered))) {
            return "unattributed_text";
        }
        return null;
    }

    private static boolean callMatches(AnalysisResult.Receipt call, AiPayload.Artifact artifact, AnalysisSubmit submit) {
        return call != null && call.state() == AnalysisResult.Receipt.CallState.VALIDATED && call.stage() == artifact.kind()
                && call.mode() == submit.mode() && POLICY_VERSION.equals(call.policyVersion())
                && call.promptVersion().equals(artifact.promptVersion()) && call.policyVersion().equals(artifact.policyVersion());
    }

    private static AnalysisResult.Receipt call(List<AnalysisResult.Receipt> receipts, String attemptId) {
        return receipts.stream().filter(r -> r.attemptId().equals(attemptId)).findFirst().orElse(null);
    }

    /** {@code reject} when prohibited advice, unsupported causality or any contradiction; {@code hold} on any gap. */
    static String semantic(AiPayload.Verification verification) {
        if (verification.prohibitedAdvice() || verification.unsupportedCausality()
                || verification.verdicts().stream().anyMatch(v -> "contradicted".equals(v.decision()))) {
            return "reject";
        }
        if (verification.verdicts().stream().anyMatch(v -> "insufficient".equals(v.decision()))) {
            return "hold";
        }
        return verification.verdicts().stream().allMatch(v -> "supported".equals(v.decision())) ? "supported" : "reject";
    }

    /**
     * The recipients the receipts prove, one per purpose: the fixed authored recipient for a replay, provider and endpoint
     * revision of the stage's call for a live job. Null when a purpose has no call: no recipient can be shown to be authorized.
     */
    private static List<String> recipients(AnalysisSubmit submit, List<AnalysisResult.Receipt> receipts) {
        if (submit.mode() == ExecutionMode.REPLAY) {
            return List.of(GrantRegistry.REPLAY_RECIPIENT);
        }
        List<String> recipients = new ArrayList<>();
        for (String purpose : GrantRegistry.purposesOf(submit.kind().wire())) {
            AnalysisResult.Receipt call = receipts.stream().filter(r -> r.stage().wire().equals(purpose)).findFirst().orElse(null);
            if (call == null) {
                return null;
            }
            recipients.add(ReceiptRecords.recipient(call));
        }
        return recipients;
    }

    /** Microsecond-precision ISO-8601 with an offset, as Python writes it; anything else is not a timestamp this app trusts. */
    private static Instant producedAt(String value) {
        try {
            Instant instant = AiPayload.instant(value);
            OffsetDateTime utc = OffsetDateTime.parse(value);
            if (instant.getNano() % 1_000 != 0 || utc.getYear() < 1 || utc.getYear() > 9_999) {
                return null;
            }
            return instant;
        } catch (StrictJson.Malformed | DateTimeException error) {
            return null;
        }
    }

    private Assessment content(Input in, ReceiptScope scope, AiPayload.Artifact main, AiPayload.Artifact verifier,
            Instant producedAt, AnalysisResult.Receipt generation, String creatorJob, List<String> recipients) {
        AnalysisSubmit submit = in.submit();
        AiPayload.Answer answer = main.answer();
        boolean summary = submit.kind() == AnalysisKind.DOCUMENT_SUMMARY;
        List<EvidenceSeed> evidence = new ArrayList<>();
        ObjectNode dto = StrictJson.newObject();
        if (summary) {
            dto.put("schemaVersion", SCHEMA);
            dto.put("artifactId", main.artifactId());
            dto.put("documentId", submit.documentId());
            dto.put("documentVersion", submit.documentVersion());
            dto.put("resultVersion", main.resultVersion());
            dto.put("text", answer.text());
            ArrayNode claims = dto.putArray("claims");
            for (AiPayload.Claim claim : answer.claims()) {
                ObjectNode node = claims.addObject();
                node.put("claimId", claim.claimId());
                node.put("text", claim.text());
                node.put("assertionKind", claim.assertionKind());
                ArrayNode ids = node.putArray("evidenceIds");
                claim.evidenceIds().forEach(id -> ids.add(evidenceId(in.analysisId(), id)));
            }
            ArrayNode citations = dto.putArray("citations");
            for (AiPayload.Citation citation : answer.citations()) {
                String id = evidenceId(in.analysisId(), citation.evidenceId());
                evidence.add(new EvidenceSeed(id, citation));
                ObjectNode node = citations.addObject();
                node.put("evidenceId", id);
                node.put("documentId", citation.documentId());
                node.put("documentVersion", citation.documentVersion());
                node.put("textArtifactId", citation.textArtifactId());
                node.put("offsetUnit", citation.offsetUnit());
                node.put("start", citation.start());
                node.put("end", citation.end());
                node.put("quote", citation.quote());
                node.put("inputKind", citation.inputKind());
                ArrayNode locators = node.putArray("rawLocatorIds");
                citation.rawLocatorIds().forEach(locators::add);
            }
            ArrayNode limitations = dto.putArray("limitations");
            answer.limitations().forEach(limitations::add);
            dto.put("producedAt", DateTimeFormatter.ISO_INSTANT.format(producedAt));
            dto.set("provenance", main.provenance().deepCopy());
        } else {
            dto.put("label", answer.label());
            dto.put("companyId", main.companyId());
            dto.put("rationale", answer.text());
            ArrayNode quotes = dto.putArray("quotes");
            answer.citations().forEach(citation -> quotes.add(citation.quote()));
            dto.put("judgedAt", DateTimeFormatter.ISO_INSTANT.format(producedAt));
            dto.put("model", generation.model());
            dto.put("promptVersion", main.promptVersion());
        }
        if (!storable(dto)) {
            return new Withheld("artifact_not_storable", scope);
        }
        String exactId = "exact-" + in.analysisId();
        ObjectNode exact = StrictJson.newObject();
        exact.put("schemaVersion", EXACT_SCHEMA);
        exact.put("analysisId", in.analysisId());
        exact.put("aiJobId", in.aiJobId());
        exact.put("creatorJobId", creatorJob);
        exact.put("kind", submit.kind().wire());
        exact.put("documentId", submit.documentId());
        exact.put("documentVersion", submit.documentVersion());
        exact.put("textArtifactId", submit.textArtifactId());
        exact.put("textSha256", in.textSha256());
        exact.put("inputDigest", main.inputDigest());
        exact.put("resultVersion", main.resultVersion());
        exact.put("policyVersion", main.policyVersion());
        ArrayNode cited = exact.putArray("citations");
        for (AiPayload.Citation citation : answer.citations()) {
            ObjectNode node = cited.addObject();
            node.put("evidenceId", summary ? evidenceId(in.analysisId(), citation.evidenceId()) : null);
            node.put("modelEvidenceId", citation.evidenceId());
            node.put("start", citation.start());
            node.put("end", citation.end());
            ArrayNode locators = node.putArray("rawLocatorIds");
            citation.rawLocatorIds().forEach(locators::add);
        }
        Content content = new Content(main, verifier, main.resultVersion(), producedAt, Canonical.write(dto),
                summary ? List.copyOf(evidence) : List.of(), exactId, Canonical.bytes(exact), generation,
                List.copyOf(recipients));
        return new Available(scope, content);
    }

    /** The app's evidence id: unique across analyses even when two models reuse the same short id. */
    static String evidenceId(String analysisId, String modelEvidenceId) {
        ObjectNode key = StrictJson.newObject();
        key.put("analysisId", analysisId);
        key.put("evidenceId", modelEvidenceId);
        return "ev-" + Canonical.digest(key);
    }

    /** Every string that is stored in a jsonb or text column must be storable (no U+0000, a UTF-8 form). */
    private static boolean storable(JsonNode node) {
        if (node.isString()) {
            return Text.storable(node.stringValue());
        }
        if (node.isObject() || node.isArray()) {
            for (JsonNode child : node.values()) {
                if (!storable(child)) {
                    return false;
                }
            }
        }
        return true;
    }

    private static AnalysisException integrity(AnalysisFailure failure, String detail) {
        return AnalysisException.of(failure, "detail", detail);
    }
}
