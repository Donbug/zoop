package com.zoop.document.bindings;

import java.util.Map;

import com.zoop.common.json.StrictJson;
import tools.jackson.databind.node.ObjectNode;

/** The result document of a run ({@code zoop-document-bindings-result-1}); it holds no path and no document content. */
final class DocumentBindingsResultWriter {
    static final String SCHEMA_VERSION = "zoop-document-bindings-result-1";

    private DocumentBindingsResultWriter() {
    }

    static byte[] toBytes(DocumentBindingsResult result) {
        ObjectNode root = StrictJson.newObject();
        root.put("schemaVersion", SCHEMA_VERSION);
        root.put("status", result.succeeded() ? "succeeded" : "failed");
        root.put("scope", result.scope().wire());
        root.put("selection", result.selected());
        if (result.succeeded()) {
            root.put("count", result.export().count());
            root.put("bytes", result.export().size());
            root.put("sha256", result.export().sha256());
            ObjectNode excluded = root.putObject("excluded");
            for (Map.Entry<String, Integer> entry : result.export().excluded().entrySet()) {
                excluded.put(entry.getKey(), entry.getValue());
            }
        } else {
            root.putObject("failure").put("code", result.failure().code());
        }
        return StrictJson.write(root);
    }
}
