package com.zoop.document.importer;

import java.time.format.DateTimeFormatter;

import com.zoop.common.json.StrictJson;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

/** The result document of a run ({@code zoop-document-import-1}); it holds no text and no path. */
final class DocumentImportResultWriter {
    private DocumentImportResultWriter() {
    }

    static byte[] toBytes(DocumentImportResult result) {
        ObjectNode root = StrictJson.newObject();
        root.put("schemaVersion", ImportRequestParser.SCHEMA_VERSION);
        root.put("status", result.succeeded() ? "succeeded" : "failed");
        if (result.requestFailure() != null) {
            root.putObject("failure").put("code", result.requestFailure().code());
        }
        ArrayNode items = root.putArray("items");
        for (ItemResult item : result.items()) {
            ObjectNode node = items.addObject();
            node.put("index", item.index());
            switch (item) {
                case ItemResult.Imported imported -> {
                    node.put("status", "imported");
                    node.put("documentId", imported.documentId());
                    node.put("documentVersion", imported.documentVersion());
                    node.put("textArtifactId", imported.textArtifactId());
                    node.put("article", imported.article().wire());
                    node.put("artifact", imported.artifact().wire());
                    node.put("artifactFile", imported.artifactFile().wire());
                    node.put("version", imported.version().wire());
                    ObjectNode pointer = node.putObject("currentVersion");
                    pointer.put("result", imported.pointer().wire());
                    pointer.put("value", imported.currentVersion());
                    node.put("collectedAt", DateTimeFormatter.ISO_INSTANT.format(imported.collectedAt()));
                    ObjectNode grant = node.putObject("grant");
                    grant.put("grantId", imported.grantId());
                    grant.put("revision", imported.grantRevision());
                }
                case ItemResult.Failed failed -> {
                    node.put("status", "failed");
                    ObjectNode failure = node.putObject("failure");
                    failure.put("code", failed.failure().code());
                    if (failed.ingestionCode() != null) {
                        failure.put("ingestionCode", failed.ingestionCode());
                    }
                    if (failed.hasCurrentVersion()) {
                        failure.put("currentVersion", failed.currentVersion());
                    }
                }
                case ItemResult.NotAttempted notAttempted -> node.put("status", "not_attempted");
            }
        }
        return StrictJson.write(root);
    }
}
