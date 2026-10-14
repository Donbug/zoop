package com.zoop.document.analysis;

import java.time.format.DateTimeFormatter;
import java.time.temporal.ChronoUnit;
import java.util.List;

import com.zoop.ai.AnalysisKind;
import com.zoop.ai.AnalysisResult;
import com.zoop.ai.ExecutionMode;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import com.zoop.document.analysis.repository.ExecutionRow;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

/**
 * What the app stores for one AI call receipt: the content-free {@code ai_call_receipt} artifact (every contract field of the
 * service's receipt plus the AI job that owns it) and the {@code ai_executions} row that counts it once.
 *
 * <p>Both are keyed by the job that CREATED the attempt ({@code creatorJobId}), never by the job that asked: a result served
 * from the artifact cache reports the creator's calls, and the same attempt must never be counted a second time.
 */
final class ReceiptRecords {
    static final String RECEIPT_SCHEMA = "zoop-app-call-receipt-1";
    static final String MEDIA_TYPE = "application/json";

    private ReceiptRecords() {
    }

    /** The one hash behind the receipt artifact id and the execution id of an attempt. */
    private static String attemptHash(String creatorJobId, String attemptId) {
        return Canonical.sha256(creatorJobId + "\n" + attemptId);
    }

    static String artifactId(String creatorJobId, String attemptId) {
        return "rcpt-" + attemptHash(creatorJobId, attemptId);
    }

    static String executionId(String creatorJobId, String attemptId) {
        return "aix-" + attemptHash(creatorJobId, attemptId);
    }

    /** The recipient a receipt proves: the fixed authored one for a replay, provider and endpoint revision for a live call. */
    static String recipient(AnalysisResult.Receipt receipt) {
        return receipt.mode() == ExecutionMode.REPLAY ? GrantRegistry.REPLAY_RECIPIENT
                : receipt.provider() + ":" + receipt.providerRevision();
    }

    /** The seven-field model configuration whose digest is the artifact's {@code modelConfigRevision}. */
    static ObjectNode configNode(AnalysisResult.Receipt receipt) {
        ObjectNode config = StrictJson.newObject();
        config.put("provider", receipt.provider());
        config.put("providerRevision", receipt.providerRevision());
        config.put("model", receipt.model());
        config.put("reasoningEffort", receipt.reasoningEffort().orElse(null));
        config.put("promptVersion", receipt.promptVersion());
        config.put("schemaVersion", receipt.schemaVersion());
        config.put("policyVersion", receipt.policyVersion());
        return config;
    }

    /** The app's canonical receipt document; deterministic, so a re-run adopts the same file. */
    static byte[] artifactBytes(String creatorJobId, AnalysisResult.Receipt receipt) {
        ObjectNode node = StrictJson.newObject();
        node.put("schemaVersion", RECEIPT_SCHEMA);
        node.put("aiJobId", creatorJobId);
        node.put("attemptId", receipt.attemptId());
        node.put("stage", receipt.stage().wire());
        node.put("state", receipt.state().name().toLowerCase(java.util.Locale.ROOT));
        node.put("mode", receipt.mode().wire());
        node.put("startedAt", DateTimeFormatter.ISO_INSTANT.format(receipt.startedAt()));
        node.put("receivedAt", receipt.receivedAt().map(DateTimeFormatter.ISO_INSTANT::format).orElse(null));
        node.put("inputDigest", receipt.inputDigest());
        node.set("config", configNode(receipt));
        if (receipt.tokens().isPresent()) {
            AnalysisResult.Receipt.Tokens tokens = receipt.tokens().get();
            ObjectNode usage = node.putObject("usage");
            usage.put("inputTokens", tokens.inputTokens());
            usage.put("outputTokens", tokens.outputTokens());
            usage.put("cachedTokens", tokens.cachedTokens());
            usage.put("reasoningTokens", tokens.reasoningTokens());
        } else {
            node.putNull("usage");
        }
        node.put("error", receipt.error().orElse(null));
        if (receipt.durationMs().isPresent()) {
            node.put("durationMs", receipt.durationMs().get());
        } else {
            node.putNull("durationMs");
        }
        return Canonical.appBytes(node);
    }

    /**
     * The execution row of one attempt. {@code documentAnalysisId} is the analysis that owns {@code creatorJobId}. A receipt
     * that is still {@code started} or {@code unknown} never reaches a settlement, so every receipt here is a result.
     */
    static ExecutionRow execution(String documentAnalysisId, String creatorJobId, AnalysisSubmit submit,
            AnalysisResult.Receipt receipt) {
        ArrayNode operations = StrictJson.newArray();
        List.of("read", "store", "model-send", "quote-display").forEach(operations::add);
        ArrayNode purposes = StrictJson.newArray();
        GrantRegistry.purposesOf(submit.kind().wire()).forEach(purposes::add);
        ArrayNode recipients = StrictJson.newArray();
        recipients.add(recipient(receipt));
        ObjectNode scope = StrictJson.newObject();
        scope.put("sourceId", submit.sourceId());
        scope.set("requiredOperations", operations);
        scope.set("requiredPurposes", purposes);
        scope.set("requiredRecipients", recipients);
        boolean failed = receipt.state() == AnalysisResult.Receipt.CallState.FAILED;
        Long input = receipt.tokens().map(AnalysisResult.Receipt.Tokens::inputTokens).orElse(null);
        Long output = receipt.tokens().map(AnalysisResult.Receipt.Tokens::outputTokens).orElse(null);
        return new ExecutionRow(executionId(creatorJobId, receipt.attemptId()), feature(receipt.stage()),
                receipt.mode().wire(), failed ? "failed" : "succeeded", documentAnalysisId, creatorJobId, receipt.attemptId(),
                receipt.stage().wire(), artifactId(creatorJobId, receipt.attemptId()), submit.grantId(),
                submit.grantRevision(), Canonical.write(scope), receipt.provider(), receipt.model(), receipt.promptVersion(),
                receipt.reasoningEffort().orElse(null), input, output, receipt.error().orElse(null),
                receipt.startedAt().truncatedTo(ChronoUnit.MICROS),
                receipt.receivedAt().map(value -> value.truncatedTo(ChronoUnit.MICROS)).orElse(null));
    }

    /**
     * ERD v6: the generation stage and the independent verification of a news document count as {@code news-analysis}; a
     * company sentiment is {@code document-sentiment}. The literal ERD attribution: the verification of a sentiment is
     * reported under {@code news-analysis}.
     */
    static String feature(AnalysisKind stage) {
        return stage == AnalysisKind.DOCUMENT_SENTIMENT ? "document-sentiment" : "news-analysis";
    }
}
