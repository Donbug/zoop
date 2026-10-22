package com.zoop.briefing.replay;

import java.util.Map;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

import static org.junit.jupiter.api.Assertions.*;

/** Authored offline artifacts only; no database, keys, provider, or network. */
class BriefingQualityPolicyTest {
    private static final String BODY = "1".repeat(64), CONTEXT = "2".repeat(64);

    private static ArrayNode history() {
        ArrayNode history = StrictJson.newArray();
        ObjectNode event = history.addObject().put("roundId", "prior-round").put("issueId", "prior-issue")
                .put("eventKey", "authored-event").put("title", "Prior authored event");
        event.putArray("companyNames").add("Authored company"); event.putArray("claims");
        event.putArray("sources").addObject().put("documentId", "prior-document").put("bodySha256", BODY)
                .put("quote", "Authored prior quote").put("evidenceId", "prior-evidence").put("url", "https://example.invalid/prior");
        return history;
    }

    private static ObjectNode round(ArrayNode history, String status, String method, String match, boolean selected) {
        ObjectNode round = StrictJson.newObject().put("identitySha256", CONTEXT);
        round.putObject("identity").put("qualityPolicy", "novelty-recovery-v2").put("noveltyHistorySha256", Canonical.digest(history));
        round.putArray("inputSources").addObject().put("documentId", "current-document")
                .put("bodySha256", "model_evidence_comparison".equals(method) ? "5".repeat(64) : BODY);
        ArrayNode selections = round.putArray("selected");
        if (selected) selections.addObject().put("issueId", "current-issue").putArray("sources").addObject().put("documentId", "current-document");
        ObjectNode audit = round.putObject("noveltyAudit").put("policy", "pass_history_event_novelty_v2")
                .put("contextSha256", CONTEXT).put("historySha256", Canonical.digest(history)).put("candidateInputSha256", "3".repeat(64))
                .put("modelCalled", "model_evidence_comparison".equals(method)).putNull("rawModelResponse")
                .put("verificationCalled", "model_evidence_comparison".equals(method)).putNull("rawVerificationResponse");
        ArrayNode ids = audit.putArray("historyIssueIds"); for (JsonNode event : history) ids.add(event.path("issueId").stringValue());
        ObjectNode decision = audit.putArray("decisions").addObject().put("documentId", "current-document").put("decision", status)
                .put("reason", "Authored reason").put("delta", "MATERIAL_UPDATE".equals(status) ? "Authored material change" : "").put("method", method);
        if (match == null) decision.putNull("matchedIssueId"); else decision.put("matchedIssueId", match);
        ArrayNode quotes = decision.putArray("quoteIds"); if ("model_evidence_comparison".equals(method)) quotes.add("authored-quote");
        boolean kept = "NEW_EVENT".equals(status) || "MATERIAL_UPDATE".equals(status);
        audit.putArray("keptDocumentIds"); audit.putArray("excludedDocumentIds");
        ((ArrayNode) audit.get(kept ? "keptDocumentIds" : "excludedDocumentIds")).add("current-document");
        if ("model_evidence_comparison".equals(method)) {
            ObjectNode rawDecision = decision.deepCopy(); rawDecision.remove("method");
            audit.putObject("rawModelResponse").putObject("decisions").set("current-document", rawDecision);
            audit.putObject("rawVerificationResponse").putObject("decisions").set("current-document", rawDecision.deepCopy());
        }
        return round;
    }

    private static Map<String, JsonNode> receipts() {
        return Map.of("4".repeat(64), StrictJson.newObject().put("stage", "round_simulation_novelty").put("status", "completed")
                .put("usageKnown", true).put("httpStatus", 200), "6".repeat(64),
                StrictJson.newObject().put("stage", "round_simulation_novelty_verification").put("status", "completed")
                        .put("usageKnown", true).put("httpStatus", 200));
    }

    private static void validate(ObjectNode round, ArrayNode history, Map<String, JsonNode> receipts) {
        BriefingReplayImporter.validateSimulationNovelty(StrictJson.Obj.of(round), history, receipts);
    }

    @Test void legacyStaysLegacyAndUnknownPoliciesFailClosed() {
        assertFalse(BriefingReplayImporter.simulationQualityV2(StrictJson.Obj.of(StrictJson.newObject())));
        ObjectNode identity = StrictJson.newObject().put("qualityPolicy", "novelty-recovery-v2").put("noveltyHistorySha256", "0".repeat(64));
        assertTrue(BriefingReplayImporter.simulationQualityV2(StrictJson.Obj.of(identity)));
        identity.put("qualityPolicy", "bypass");
        assertThrows(IllegalArgumentException.class, () -> BriefingReplayImporter.simulationQualityV2(StrictJson.Obj.of(identity)));
        ObjectNode stray = StrictJson.newObject().put("noveltyHistorySha256", "0".repeat(64));
        assertThrows(IllegalArgumentException.class, () -> BriefingReplayImporter.simulationQualityV2(StrictJson.Obj.of(stray)));
    }

    @Test void firstRoundUsesNoModelAndPreservesItsInput() {
        ArrayNode history = StrictJson.newArray(); ObjectNode round = round(history, "NEW_EVENT", "no_history_no_model", null, true);
        byte[] before = StrictJson.write(round); validate(round, history, Map.of()); assertArrayEquals(before, StrictJson.write(round));
    }

    @Test void exactBodyRepeatIsHeldAndCannotBeSelected() {
        ArrayNode history = history(); ObjectNode round = round(history, "REPEAT", "deterministic_body_digest", "prior-issue", false);
        validate(round, history, Map.of());
        ((ArrayNode) round.get("selected")).addObject().putArray("sources").addObject().put("documentId", "current-document");
        assertThrows(IllegalArgumentException.class, () -> validate(round, history, Map.of()));
    }

    @Test void uncertainModelDecisionCannotBeSelected() {
        ArrayNode history = history(); ObjectNode round = round(history, "UNCERTAIN", "model_evidence_comparison", null, false);
        validate(round, history, receipts());
        ((ArrayNode) round.get("selected")).addObject().putArray("sources").addObject().put("documentId", "current-document");
        assertThrows(IllegalArgumentException.class, () -> validate(round, history, receipts()));
    }

    @Test void materialUpdateNeedsKnownPriorIssueAndNonemptyDelta() {
        ArrayNode history = history(); ObjectNode round = round(history, "MATERIAL_UPDATE", "model_evidence_comparison", "prior-issue", true);
        validate(round, history, receipts());
        ObjectNode decision = (ObjectNode) round.path("noveltyAudit").path("decisions").get(0); decision.put("delta", "");
        assertThrows(IllegalArgumentException.class, () -> validate(round, history, receipts()));
        ObjectNode invented = round(history, "MATERIAL_UPDATE", "model_evidence_comparison", "future-or-invented-issue", true);
        assertThrows(IllegalArgumentException.class, () -> validate(invented, history, receipts()));
    }

    @Test void historyAndContextHashesCannotDrift() {
        ArrayNode history = history(); ObjectNode wrongHistory = round(history, "REPEAT", "deterministic_body_digest", "prior-issue", false);
        ((ObjectNode) wrongHistory.path("identity")).put("noveltyHistorySha256", "0".repeat(64));
        assertThrows(IllegalArgumentException.class, () -> validate(wrongHistory, history, Map.of()));
        ObjectNode drift = round(history, "REPEAT", "deterministic_body_digest", "prior-issue", false);
        ((ObjectNode) drift.path("noveltyAudit")).put("contextSha256", "0".repeat(64));
        assertThrows(IllegalArgumentException.class, () -> validate(drift, history, Map.of()));
    }

    @Test void auditCannotRewriteModelDecisionOrOmitItsReceipt() {
        ArrayNode history = history(); ObjectNode round = round(history, "NEW_EVENT", "model_evidence_comparison", null, true);
        assertThrows(IllegalArgumentException.class, () -> validate(round, history, Map.of()));
        ((ObjectNode) round.path("noveltyAudit").path("rawVerificationResponse").path("decisions").path("current-document")).put("decision", "REPEAT");
        assertThrows(IllegalArgumentException.class, () -> validate(round, history, receipts()));
    }

    @Test void independentVerifierMayCorrectInitialMatcherButFinalDecisionMustMatchVerifier() {
        ArrayNode history = history(); ObjectNode round = round(history, "NEW_EVENT", "model_evidence_comparison", null, true);
        ObjectNode initial = (ObjectNode) round.path("noveltyAudit").path("rawModelResponse").path("decisions").path("current-document");
        initial.put("decision", "REPEAT").put("matchedIssueId", "prior-issue");
        validate(round, history, receipts());
        ((ObjectNode) round.path("noveltyAudit")).put("verificationCalled", false);
        assertThrows(IllegalArgumentException.class, () -> validate(round, history, receipts()));
    }

    @Test void missingIndependentVerifierReceiptCannotPublish() {
        ArrayNode history = history(); ObjectNode round = round(history, "NEW_EVENT", "model_evidence_comparison", null, true);
        Map<String, JsonNode> onlyInitial = Map.of("4".repeat(64), receipts().get("4".repeat(64)));
        assertThrows(IllegalArgumentException.class, () -> validate(round, history, onlyInitial));
        Map<String, JsonNode> onlyVerifier = Map.of("6".repeat(64), receipts().get("6".repeat(64)));
        assertThrows(IllegalArgumentException.class, () -> validate(round, history, onlyVerifier));
    }

    @Test void deterministicHistoryCaseCannotInventIndependentVerification() {
        ArrayNode history = StrictJson.newArray(); ObjectNode round = round(history, "NEW_EVENT", "no_history_no_model", null, true);
        ((ObjectNode) round.path("noveltyAudit")).put("verificationCalled", true);
        assertThrows(IllegalArgumentException.class, () -> validate(round, history, Map.of()));
    }

    @Test void keptPartitionAndHistoryIdsMustExactlyMatchDecisions() {
        ArrayNode history = history(); ObjectNode round = round(history, "REPEAT", "deterministic_body_digest", "prior-issue", false);
        ((ArrayNode) round.path("noveltyAudit").path("keptDocumentIds")).add("current-document");
        assertThrows(IllegalArgumentException.class, () -> validate(round, history, Map.of()));
        ObjectNode wrongHistory = round(history, "REPEAT", "deterministic_body_digest", "prior-issue", false);
        ((ArrayNode) wrongHistory.path("noveltyAudit").path("historyIssueIds")).add("unknown-issue");
        assertThrows(IllegalArgumentException.class, () -> validate(wrongHistory, history, Map.of()));
    }

    @Test void selectedRoundCannotOmitNoveltyAudit() {
        ArrayNode history = StrictJson.newArray(); ObjectNode round = round(history, "NEW_EVENT", "no_history_no_model", null, true); round.remove("noveltyAudit");
        assertThrows(IllegalArgumentException.class, () -> validate(round, history, Map.of()));
    }

    @Test void historyProjectionMatchesPublishedSourceAndGeneratedOutput() {
        ObjectNode round = StrictJson.newObject().put("selectionStatus", "SELECTED").put("roundId", "prior-round");
        ObjectNode selected = round.putArray("selected").addObject().put("issueId", "prior-issue").put("eventKey", "authored-event");
        selected.putArray("companyNames").add("Authored company");
        selected.putArray("sources").add(history().get(0).path("sources").get(0).deepCopy());
        ObjectNode result = round.putObject("result"); result.putObject("verification").put("status", "PASS");
        result.putArray("items").addObject().put("issueId", "prior-issue").put("title", "Prior authored event").putArray("claims");
        ArrayNode actual = StrictJson.newArray(); BriefingReplayImporter.appendSimulationNoveltyHistory(actual, StrictJson.Obj.of(round));
        assertEquals(history(), actual);
        ((ObjectNode) result.get("verification")).put("status", "FAIL");
        assertThrows(IllegalArgumentException.class, () -> BriefingReplayImporter.appendSimulationNoveltyHistory(actual, StrictJson.Obj.of(round)));
    }
}
