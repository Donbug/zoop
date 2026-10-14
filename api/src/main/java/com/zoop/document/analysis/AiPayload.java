package com.zoop.document.analysis;

import java.time.DateTimeException;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import java.util.regex.Pattern;

import com.zoop.ai.AnalysisKind;
import com.zoop.ai.AnalysisResult;
import com.zoop.ai.ExecutionMode;
import com.zoop.common.json.StrictJson;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ObjectNode;

/**
 * The untrusted job payload of an {@code available} result ({@code JobResult} of {@code zoop-ai-s1-1}) read into typed values.
 * Only the parts the app checks and stores are taken: the echoed submit, the artifacts (their key sets are closed), the calls
 * and the ids. Nothing here is a decision; {@link ResultAssessor} makes them.
 *
 * <p>Any shape violation is {@link StrictJson.Malformed}: the payload does not satisfy the contract it claims, so nothing about
 * it can be settled.
 */
record AiPayload(String schemaVersion, String jobId, String inputDigest, String state, String phase, List<String> artifactIds,
        List<Artifact> artifacts, JsonNode input, List<AnalysisResult.Receipt> calls) {

    private static final Set<String> TOP = Set.of("schemaVersion", "jobId", "inputDigest", "state", "phase", "artifactIds",
            "artifacts", "input", "calls");
    private static final Set<String> ARTIFACT = Set.of("schemaVersion", "artifactId", "kind", "resultVersion", "jobId",
            "attemptId", "inputDigest", "sourceRefs", "dependencyRefs", "modelConfigRevision", "promptVersion", "policyVersion",
            "producedAt", "provenance", "companyId", "grantId", "grantRevision", "claims", "validation", "result");
    private static final Set<String> VALIDATION = Set.of("exact", "semantic", "eligible", "reason");
    private static final Set<String> CLAIM = Set.of("claimId", "text", "assertionKind", "evidenceIds");
    private static final Set<String> CITATION = Set.of("evidenceId", "documentId", "documentVersion", "textArtifactId",
            "offsetUnit", "start", "end", "quote", "inputKind", "rawLocatorIds");
    private static final Set<String> CALL = Set.of("attemptId", "stage", "state", "mode", "startedAt", "receivedAt", "inputDigest",
            "config", "usage", "error", "durationMs");
    private static final Set<String> CONFIG = Set.of("provider", "providerRevision", "model", "reasoningEffort", "promptVersion",
            "schemaVersion", "policyVersion");
    private static final Set<String> USAGE = Set.of("inputTokens", "outputTokens", "cachedTokens", "reasoningTokens");
    private static final Pattern STAMP = Pattern.compile(
            "[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\\.[0-9]{1,9})?(Z|[+-][0-9]{2}:[0-9]{2})");

    /** One claim of an answer: free text plus the ids of the citations that support it. */
    record Claim(String claimId, String text, String assertionKind, List<String> evidenceIds) {
    }

    /** One citation of an answer: a quote at code point offsets of the document text. */
    record Citation(String evidenceId, String documentId, String documentVersion, String textArtifactId, String offsetUnit,
            int start, int end, String quote, String inputKind, List<String> rawLocatorIds) {
    }

    record Verdict(String claimId, String decision) {
    }

    /** The answer of a summary or sentiment artifact; {@code text} is the summary text or the sentiment rationale. */
    record Answer(String label, String text, List<Claim> claims, List<Citation> citations, List<String> limitations) {
    }

    /** The answer of a semantic-verification artifact. */
    record Verification(List<Verdict> verdicts, boolean prohibitedAdvice, boolean unsupportedCausality) {
    }

    record Validation(boolean exact, String semantic, boolean eligible, String reason) {
    }

    /**
     * One AI artifact. {@code node} is the object exactly as delivered (the content that is stored and digested);
     * {@code answer} is set for a document kind and {@code verification} for the verifier.
     */
    record Artifact(ObjectNode node, String schemaVersion, String artifactId, AnalysisKind kind, String resultVersion,
            String jobId, String attemptId, String inputDigest, List<JsonNode> sourceRefs, List<String> dependencyRefs,
            String modelConfigRevision, String promptVersion, String policyVersion, String producedAt, JsonNode provenance,
            String companyId, String grantId, String grantRevision, JsonNode claimsNode, List<Claim> claims,
            Validation validation, JsonNode resultNode, Answer answer, Verification verification) {
    }

    static AiPayload parse(String json) {
        StrictJson.Obj top = StrictJson.parseObject(json).requiring(TOP);
        List<Artifact> artifacts = new ArrayList<>();
        for (StrictJson.Obj artifact : top.objects("artifacts")) {
            artifacts.add(artifact(artifact));
        }
        List<AnalysisResult.Receipt> calls = new ArrayList<>();
        for (StrictJson.Obj call : top.objects("calls")) {
            calls.add(receipt(call));
        }
        return new AiPayload(top.string("schemaVersion"), top.string("jobId"), top.string("inputDigest"), top.string("state"),
                top.string("phase"), top.strings("artifactIds"), artifacts, top.raw("input"), calls);
    }

    private static Artifact artifact(StrictJson.Obj obj) {
        obj.exactly(ARTIFACT);
        AnalysisKind kind = AnalysisKind.fromWire(obj.string("kind")).orElseThrow(StrictJson.Malformed::new);
        StrictJson.Obj validation = obj.object("validation").exactly(VALIDATION);
        List<JsonNode> sourceRefs = new ArrayList<>();
        obj.array("sourceRefs").values().forEach(sourceRefs::add);
        StrictJson.Obj result = obj.object("result");
        Answer answer = null;
        Verification verification = null;
        if (kind == AnalysisKind.SEMANTIC_VERIFICATION) {
            verification = verification(result);
        } else if (kind == AnalysisKind.DOCUMENT_SUMMARY || kind == AnalysisKind.DOCUMENT_SENTIMENT) {
            answer = answer(kind, result);
        } else {
            throw new StrictJson.Malformed();
        }
        return new Artifact((ObjectNode) obj.node(), obj.string("schemaVersion"), obj.string("artifactId"), kind,
                obj.string("resultVersion"), obj.string("jobId"), obj.string("attemptId"), obj.string("inputDigest"), sourceRefs,
                obj.strings("dependencyRefs"), obj.string("modelConfigRevision"), obj.string("promptVersion"),
                obj.string("policyVersion"), obj.string("producedAt"), obj.raw("provenance"), obj.stringOrNull("companyId"),
                obj.string("grantId"), obj.string("grantRevision"), obj.raw("claims"), claims(obj.objects("claims")),
                new Validation(validation.bool("exact"), validation.stringOrNull("semantic"), validation.bool("eligible"),
                        validation.stringOrNull("reason")),
                result.node(), answer, verification);
    }

    private static List<Claim> claims(List<StrictJson.Obj> objects) {
        List<Claim> claims = new ArrayList<>();
        for (StrictJson.Obj claim : objects) {
            claim.exactly(CLAIM);
            claims.add(new Claim(claim.string("claimId"), claim.string("text"), claim.string("assertionKind"),
                    claim.strings("evidenceIds")));
        }
        return claims;
    }

    private static Answer answer(AnalysisKind kind, StrictJson.Obj result) {
        boolean summary = kind == AnalysisKind.DOCUMENT_SUMMARY;
        result.exactly(summary ? Set.of("text", "claims", "citations", "limitations")
                : Set.of("label", "rationale", "claims", "citations", "limitations"));
        List<Citation> citations = new ArrayList<>();
        for (StrictJson.Obj citation : result.objects("citations")) {
            citation.exactly(CITATION);
            citations.add(new Citation(citation.string("evidenceId"), citation.string("documentId"),
                    citation.string("documentVersion"), citation.string("textArtifactId"), citation.string("offsetUnit"),
                    citation.count("start"), citation.count("end"), citation.string("quote"), citation.string("inputKind"),
                    citation.strings("rawLocatorIds")));
        }
        return new Answer(summary ? null : result.string("label"), result.string(summary ? "text" : "rationale"),
                claims(result.objects("claims")), citations, result.strings("limitations"));
    }

    private static Verification verification(StrictJson.Obj result) {
        result.exactly(Set.of("claims", "prohibitedAdvice", "unsupportedCausality"));
        List<Verdict> verdicts = new ArrayList<>();
        for (StrictJson.Obj verdict : result.objects("claims")) {
            verdict.exactly(Set.of("claimId", "decision", "reason"));
            verdict.string("reason");
            verdicts.add(new Verdict(verdict.string("claimId"), verdict.string("decision")));
        }
        return new Verification(verdicts, result.bool("prohibitedAdvice"), result.bool("unsupportedCausality"));
    }

    /** One {@code calls[]} entry in the same typed form as the service's result receipts, so the two can be compared. */
    static AnalysisResult.Receipt receipt(StrictJson.Obj call) {
        call.exactly(CALL);
        StrictJson.Obj config = call.object("config").exactly(CONFIG);
        Optional<AnalysisResult.Receipt.Tokens> tokens = Optional.empty();
        if (!call.isNull("usage")) {
            StrictJson.Obj usage = call.object("usage").exactly(USAGE);
            tokens = Optional.of(new AnalysisResult.Receipt.Tokens(token(usage, "inputTokens"), token(usage, "outputTokens"),
                    token(usage, "cachedTokens"), token(usage, "reasoningTokens")));
        }
        Optional<Double> duration = Optional.empty();
        JsonNode durationNode = call.raw("durationMs");
        if (!durationNode.isNull()) {
            if (!durationNode.isNumber() || !Double.isFinite(durationNode.doubleValue()) || durationNode.doubleValue() < 0) {
                throw new StrictJson.Malformed();
            }
            duration = Optional.of(durationNode.doubleValue());
        }
        AnalysisResult.Receipt.CallState state;
        try {
            state = AnalysisResult.Receipt.CallState.valueOf(call.string("state").toUpperCase(java.util.Locale.ROOT));
        } catch (IllegalArgumentException error) {
            throw new StrictJson.Malformed();
        }
        return new AnalysisResult.Receipt(call.string("attemptId"),
                AnalysisKind.fromWire(call.string("stage")).orElseThrow(StrictJson.Malformed::new), state,
                ExecutionMode.fromWire(call.string("mode")).orElseThrow(StrictJson.Malformed::new),
                instant(call.string("startedAt")), Optional.ofNullable(call.stringOrNull("receivedAt")).map(AiPayload::instant),
                call.string("inputDigest"), tokens, Optional.ofNullable(call.stringOrNull("error")), duration,
                config.string("provider"), config.string("providerRevision"), config.string("model"),
                Optional.ofNullable(config.stringOrNull("reasoningEffort")), config.string("promptVersion"),
                config.string("schemaVersion"), config.string("policyVersion"));
    }

    private static Long token(StrictJson.Obj usage, String name) {
        JsonNode value = usage.raw(name);
        if (value.isNull()) {
            return null;
        }
        if (!value.isIntegralNumber() || !value.canConvertToLong() || value.longValue() < 0) {
            throw new StrictJson.Malformed();
        }
        return value.longValue();
    }

    /** ISO-8601 with an explicit offset, as the runtime ledger writes receipt times. */
    static Instant instant(String value) {
        if (!STAMP.matcher(value).matches()) {
            throw new StrictJson.Malformed();
        }
        try {
            return OffsetDateTime.parse(value).toInstant();
        } catch (DateTimeException error) {
            throw new StrictJson.Malformed();
        }
    }
}
