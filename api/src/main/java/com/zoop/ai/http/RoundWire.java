package com.zoop.ai.http;

import java.util.Optional;
import java.util.Set;
import java.util.regex.Pattern;

import com.zoop.ai.RoundServiceErrorException;
import com.zoop.ai.http.WireJson.Malformed;
import com.zoop.ai.round.RoundHandoffClient.RoundHandoff;
import com.zoop.ai.round.RoundRunClient.RoundRun;
import tools.jackson.databind.JsonNode;

/**
 * The round families' wire (#387 ①②, contract proposal of 2026-10-30): the two request schemas, the closed status documents
 * and the shared {@code ErrorEnvelope}. Every status document is decoded strictly: known keys only, the requested round id
 * echoed, the state one of the contract's, and the fields a state promises present. Unknown codes are kept (they are the
 * service's), unknown states are refused.
 */
final class RoundWire {
    static final String RUN_SCHEMA = "zoop-ai-round-run-1";
    static final String HANDOFF_SCHEMA = "zoop-ai-round-handoff-1";
    /** The app's slot id ({@code graph_rounds.round_id}). */
    static final Pattern ROUND_ID = Pattern.compile("round-[0-9]{8}T[0-9]{4}");
    /** The AI ingestion round id the tick makes ({@code slot-<sha256>}), or any other id the AI side chooses for it. */
    static final Pattern INGESTION_ROUND_ID = Pattern.compile("[A-Za-z0-9._:-]{1,200}");
    static final Pattern PLAN_ID = Pattern.compile("s2plan-[0-9a-f]{64}");
    static final Pattern HASH = Pattern.compile("[a-f0-9]{64}");
    private static final Set<String> RUN_KEYS = Set.of("schemaVersion", "roundId", "state", "ingestionRoundId", "planId",
            "planDigest", "code", "observedAt");
    private static final Set<String> HANDOFF_KEYS = Set.of("schemaVersion", "roundId", "state", "handoffId", "manifestDigest",
            "bundleDigest", "selection", "code", "observedAt");

    private RoundWire() {
    }

    static RoundRun run(JsonNode document, String roundId) {
        WireJson.Obj root = status(document, roundId, RUN_SCHEMA, RUN_KEYS);
        RoundRun.State state = RoundRun.State.parse(root.string("state", AnalysisWire.CODE))
                .orElseThrow(() -> new Malformed("roundRun.state"));
        Optional<String> ingestion = optional(root, document, "ingestionRoundId", INGESTION_ROUND_ID);
        Optional<String> planId = optional(root, document, "planId", PLAN_ID);
        Optional<String> planDigest = optional(root, document, "planDigest", HASH);
        Optional<String> code = optional(root, document, "code", AnalysisWire.CODE);
        if (planId.isPresent() != planDigest.isPresent()) throw new Malformed("roundRun.planDigest");
        if (state == RoundRun.State.READY && (ingestion.isEmpty() || planId.isEmpty())) throw new Malformed("roundRun.planId");
        if (state != RoundRun.State.READY && planId.isPresent()) throw new Malformed("roundRun.planId");
        if ((state == RoundRun.State.FAILED || state == RoundRun.State.NO_NEW_MATERIAL) && code.isEmpty()) {
            throw new Malformed("roundRun.code");
        }
        return new RoundRun(roundId, state, ingestion, planId, planDigest, code);
    }

    static RoundHandoff handoff(JsonNode document, String roundId) {
        WireJson.Obj root = status(document, roundId, HANDOFF_SCHEMA, HANDOFF_KEYS);
        RoundHandoff.State state = RoundHandoff.State.parse(root.string("state", AnalysisWire.CODE))
                .orElseThrow(() -> new Malformed("roundHandoff.state"));
        Optional<String> handoffId = optional(root, document, "handoffId", HandoffWire.HANDOFF_ID);
        Optional<String> manifest = optional(root, document, "manifestDigest", HASH);
        Optional<String> bundle = optional(root, document, "bundleDigest", HASH);
        Optional<String> code = optional(root, document, "code", AnalysisWire.CODE);
        JsonNode selectionNode = document.get("selection");
        Optional<JsonNode> selection = selectionNode == null || selectionNode.isNull() ? Optional.empty() : Optional.of(selectionNode);
        if (selection.isPresent() && !selectionNode.isObject()) throw new Malformed("roundHandoff.selection");
        boolean ready = state == RoundHandoff.State.READY;
        if (ready && (handoffId.isEmpty() || manifest.isEmpty() || bundle.isEmpty())) throw new Malformed("roundHandoff.handoffId");
        if (!ready && (handoffId.isPresent() || manifest.isPresent() || bundle.isPresent())) throw new Malformed("roundHandoff.handoffId");
        if ((state == RoundHandoff.State.FAILED || state == RoundHandoff.State.ANALYSIS_INCOMPLETE
                || state == RoundHandoff.State.NO_PUBLIC_MATERIAL) && code.isEmpty()) {
            throw new Malformed("roundHandoff.code");
        }
        if (state == RoundHandoff.State.NO_PUBLIC_MATERIAL
                && (!code.orElse("").equals("window_empty") || selection.isEmpty())) {
            throw new Malformed("roundHandoff.selection");
        }
        return new RoundHandoff(roundId, state, handoffId, manifest, bundle, selection, code);
    }

    /** The closed status object: one of the family's schemas when present, the requested round id, known keys only. */
    private static WireJson.Obj status(JsonNode document, String roundId, String schema, Set<String> keys) {
        if (document == null || !document.isObject() || !keys.containsAll(HandoffWire.names(document))) {
            throw new Malformed("round");
        }
        JsonNode declared = document.get("schemaVersion");
        if (declared != null && (!declared.isString() || !schema.equals(declared.stringValue()))) {
            throw new Malformed("round.schemaVersion");
        }
        WireJson.Obj root = WireJson.Obj.of(document, "round");
        if (!root.string("roundId", ROUND_ID).equals(roundId)) throw new Malformed("round.roundId");
        return root;
    }

    private static Optional<String> optional(WireJson.Obj root, JsonNode document, String name, Pattern pattern) {
        return document.has(name) ? root.optString(name, pattern) : Optional.empty();
    }

    /** {@code ErrorEnvelope} under the generic internal schema; {@code status} (a job status elsewhere) may be present only as null. */
    static AiHttpTransport.Rejections rejections() {
        return (document, status, retryAfter, operation, requestId) -> {
            if (document == null || !document.isObject() || !document.has("error")
                    || !Set.of("schemaVersion", "error", "status").containsAll(HandoffWire.names(document))) {
                throw new Malformed("error");
            }
            JsonNode declared = document.get("schemaVersion");
            if (declared != null && (!declared.isString() || !AnalysisWire.INTERNAL_SCHEMA.equals(declared.stringValue()))) {
                throw new Malformed("error.schemaVersion");
            }
            if (document.has("status") && !document.get("status").isNull()) throw new Malformed("error.status");
            JsonNode error = document.get("error");
            if (!error.isObject() || !Set.of("code", "retryable", "requestId", "runtimeCode", "field").containsAll(HandoffWire.names(error))) {
                throw new Malformed("error");
            }
            WireJson.Obj body = WireJson.Obj.of(error, "error");
            if (!body.string("requestId", AnalysisWire.REQUEST_ID).equals(requestId)) throw new Malformed("error.requestId");
            return new RoundServiceErrorException(operation, requestId, status, body.string("code", AnalysisWire.CODE),
                    body.bool("retryable"), error.has("runtimeCode") ? body.optString("runtimeCode", AnalysisWire.TEXT) : Optional.empty(),
                    error.has("field") ? body.optString("field", AnalysisWire.TEXT) : Optional.empty(), retryAfter);
        };
    }
}
