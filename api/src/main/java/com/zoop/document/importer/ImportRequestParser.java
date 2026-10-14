package com.zoop.document.importer;

import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.regex.Pattern;

import com.zoop.common.json.StrictJson;
import com.zoop.common.json.Text;
import com.zoop.document.DocumentImportException;
import com.zoop.document.DocumentImportFailure;
import com.zoop.document.service.ArticleKind;
import com.zoop.document.service.PointerPolicy;
import tools.jackson.databind.JsonNode;

/**
 * Parses the operator request ({@code zoop-document-import-1}). The schema is closed: an unknown or duplicate key, a wrong
 * type, an out-of-range value or an oversized file is {@code request_invalid}. There is deliberately no key through which
 * an export, text, grant or path could be supplied. {@code currentVersion} distinguishes three cases: absent (insertion
 * only), {@code {"expected": null}} (the article must have no current version) and {@code {"expected": "<64hex>"}}; a
 * bare {@code null} or an object without {@code expected} is invalid.
 */
public final class ImportRequestParser {
    public static final String SCHEMA_VERSION = "zoop-document-import-1";
    public static final int MAX_BYTES = 1 << 20;

    private static final Pattern DOCUMENT_ID = Pattern.compile("doc-[0-9a-f]{64}");
    private static final int MAX_ID_CODE_POINTS = 200;

    public ImportRequest parse(byte[] bytes) {
        if (bytes.length == 0 || bytes.length > MAX_BYTES) {
            throw invalid();
        }
        try {
            StrictJson.Obj root = StrictJson.parseObject(bytes).exactly(Set.of("schemaVersion", "items"));
            if (!SCHEMA_VERSION.equals(root.string("schemaVersion"))) {
                throw invalid();
            }
            JsonNode items = root.array("items");
            if (items.size() == 0 || items.size() > ImportRequest.MAX_ITEMS) {
                throw invalid();
            }
            List<ImportItem> parsed = new ArrayList<>(items.size());
            for (JsonNode item : items.values()) {
                parsed.add(item(StrictJson.Obj.of(item)));
            }
            return new ImportRequest(List.copyOf(parsed));
        } catch (StrictJson.Malformed malformed) {
            throw invalid();
        }
    }

    private static ImportItem item(StrictJson.Obj item) {
        item.keys(Set.of("kind", "observation"), Set.of("currentVersion"));
        ArticleKind kind = ArticleKind.fromWire(item.string("kind")).orElseThrow(ImportRequestParser::invalid);
        StrictJson.Obj observation = item.object("observation").exactly(
                Set.of("roundId", "sourceId", "page", "ordinal", "documentId", "rawVersion", "documentVersion"));
        PointerPolicy pointer = PointerPolicy.keep();
        if (item.has("currentVersion")) {
            StrictJson.Obj current = item.object("currentVersion").exactly(Set.of("expected"));
            String expected = current.stringOrNull("expected");
            if (expected != null && !StrictJson.SHA256.matcher(expected).matches()) {
                throw invalid();
            }
            pointer = PointerPolicy.moveFrom(expected);
        }
        return new ImportItem(kind, new Observation(
                identifier(observation.string("roundId")),
                identifier(observation.string("sourceId")),
                observation.count("page"),
                observation.count("ordinal"),
                match(observation.string("documentId"), DOCUMENT_ID),
                match(observation.string("rawVersion"), StrictJson.SHA256),
                match(observation.string("documentVersion"), StrictJson.SHA256)), pointer);
    }

    /** 1 to 200 code points, well-formed, storable (sourceId becomes {@code articles.provider}). */
    private static String identifier(String value) {
        if (value.isEmpty() || Text.codePoints(value) > MAX_ID_CODE_POINTS || !Text.storable(value)) {
            throw invalid();
        }
        return value;
    }

    private static String match(String value, Pattern pattern) {
        if (!pattern.matcher(value).matches()) {
            throw invalid();
        }
        return value;
    }

    private static DocumentImportException invalid() {
        return new DocumentImportException(DocumentImportFailure.REQUEST_INVALID);
    }
}
