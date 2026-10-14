package com.zoop.document.analysis;

import java.util.Map;
import java.util.TreeMap;

import com.zoop.common.json.StrictJson;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

/** The result document of a run ({@code zoop-document-analysis-1}); it holds no text, no path and no model output. */
final class AnalysisResultWriter {
    private AnalysisResultWriter() {
    }

    static byte[] toBytes(AnalysisRunResult result) {
        ObjectNode root = StrictJson.newObject();
        root.put("schemaVersion", AnalysisRequestParser.SCHEMA_VERSION);
        root.put("command", result.command());
        root.put("status", result.succeeded() ? "succeeded" : "failed");
        if (result.requestFailure() != null) {
            failure(root.putObject("failure"), result.requestFailure(), result.requestDetails());
        }
        ArrayNode items = root.putArray("items");
        for (AnalysisItemResult item : result.items()) {
            ObjectNode node = items.addObject();
            node.put("index", item.index());
            switch (item) {
                case AnalysisItemResult.Prepared prepared -> {
                    node.put("status", "prepared");
                    node.put("analysisId", prepared.analysisId());
                    node.put("aiJobId", prepared.aiJobId());
                    node.put("requestNo", prepared.requestNo());
                    node.put("stage", prepared.stage());
                }
                case AnalysisItemResult.Settled settled -> {
                    node.put("status", "settled");
                    node.put("analysisId", settled.analysisId());
                    node.put("outcome", settled.outcome());
                    node.put("reason", settled.reason());
                    ObjectNode executions = node.putObject("executions");
                    executions.put("recorded", settled.executionsRecorded());
                    executions.put("existing", settled.executionsExisting());
                    node.put("evidence", settled.evidence());
                }
                case AnalysisItemResult.Pending pending -> {
                    node.put("status", "pending");
                    node.put("analysisId", pending.analysisId());
                    node.put("aiJobId", pending.aiJobId());
                    node.put("waiting", pending.waiting());
                }
                case AnalysisItemResult.AlreadySettled already -> {
                    node.put("status", "already_settled");
                    node.put("analysisId", already.analysisId());
                    node.put("outcome", already.outcome());
                    node.put("reason", already.reason());
                }
                case AnalysisItemResult.Failed failed -> {
                    node.put("status", "failed");
                    failure(node.putObject("failure"), failed.failure(), failed.details());
                }
                case AnalysisItemResult.NotAttempted notAttempted -> node.put("status", "not_attempted");
            }
        }
        return StrictJson.write(root);
    }

    private static void failure(ObjectNode node, AnalysisFailure failure, Map<String, String> details) {
        node.put("code", failure.code());
        // A stable order, so that two runs of the same failure write the same bytes.
        new TreeMap<>(details).forEach((key, value) -> node.put(key, value));
    }
}
