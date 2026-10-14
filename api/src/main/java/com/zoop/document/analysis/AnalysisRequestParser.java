package com.zoop.document.analysis;

import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.regex.Pattern;

import com.zoop.ai.AnalysisKind;
import com.zoop.ai.ExecutionMode;
import com.zoop.common.json.StrictJson;
import com.zoop.common.json.Text;
import com.zoop.document.importer.Observation;
import tools.jackson.databind.JsonNode;

/**
 * Parses the operator request ({@code zoop-document-analysis-1}). The schema is closed: an unknown or duplicate key, a wrong
 * type, an out-of-range value or an oversized file is {@code request_invalid}. There is deliberately no key through which a
 * document text, an export, a grant, a model output or a path could be supplied: the document comes from a fresh S2-1 export,
 * the rights from the operator's registry files, the company's name from the catalog.
 *
 * <p>{@code prepare} items select the document and declare kind, company, grant, mode and source kind; {@code latest} is
 * required and is {@code {"expected": null}} for the first analysis of a scope or {@code {"expected": "da-..."}} for a
 * re-request. {@code advance} items name a reserved analysis and may set {@code recover}.
 */
public final class AnalysisRequestParser {
    public static final String SCHEMA_VERSION = "zoop-document-analysis-1";
    public static final int MAX_BYTES = 1 << 20;

    private static final Pattern DOCUMENT_ID = Pattern.compile("doc-[0-9a-f]{64}");
    private static final Pattern ANALYSIS_ID = Pattern.compile("da-[0-9a-f]{32}");
    private static final int MAX_ID_CODE_POINTS = 200;
    private static final int MAX_GRANT_CODE_POINTS = 1_000;

    public AnalysisRequest parse(byte[] bytes) {
        if (bytes.length == 0 || bytes.length > MAX_BYTES) {
            throw invalid();
        }
        try {
            StrictJson.Obj root = StrictJson.parseObject(bytes).exactly(Set.of("schemaVersion", "command", "items"));
            if (!SCHEMA_VERSION.equals(root.string("schemaVersion"))) {
                throw invalid();
            }
            String command = root.string("command");
            JsonNode items = root.array("items");
            if (items.size() == 0 || items.size() > AnalysisRequest.MAX_ITEMS) {
                throw invalid();
            }
            if (command.equals("prepare")) {
                List<AnalysisRequest.PrepareItem> parsed = new ArrayList<>(items.size());
                for (JsonNode item : items.values()) {
                    parsed.add(prepare(StrictJson.Obj.of(item)));
                }
                return new AnalysisRequest.Prepare(parsed);
            }
            if (command.equals("advance")) {
                List<AnalysisRequest.AdvanceItem> parsed = new ArrayList<>(items.size());
                for (JsonNode item : items.values()) {
                    parsed.add(advance(StrictJson.Obj.of(item)));
                }
                return new AnalysisRequest.Advance(parsed);
            }
            throw invalid();
        } catch (StrictJson.Malformed malformed) {
            throw invalid();
        }
    }

    private static AnalysisRequest.PrepareItem prepare(StrictJson.Obj item) {
        item.exactly(Set.of("observation", "kind", "companyId", "grant", "mode", "sourceKind", "latest"));
        AnalysisKind kind = AnalysisKind.fromWire(item.string("kind")).orElseThrow(AnalysisRequestParser::invalid);
        if (kind != AnalysisKind.DOCUMENT_SUMMARY && kind != AnalysisKind.DOCUMENT_SENTIMENT) {
            throw invalid();
        }
        ExecutionMode mode = ExecutionMode.fromWire(item.string("mode")).orElseThrow(AnalysisRequestParser::invalid);
        String sourceKind = item.string("sourceKind");
        if (!sourceKind.equals("synthetic") && !sourceKind.equals("actual")) {
            throw invalid();
        }
        if (mode == ExecutionMode.REPLAY && !sourceKind.equals("synthetic")) {
            // The worker only replays authored, synthetic documents; actual text needs a live provider run.
            throw invalid();
        }
        StrictJson.Obj observation = item.object("observation").exactly(
                Set.of("roundId", "sourceId", "page", "ordinal", "documentId", "rawVersion", "documentVersion"));
        StrictJson.Obj grant = item.object("grant").exactly(Set.of("grantId", "revision"));
        String expected = item.object("latest").exactly(Set.of("expected")).stringOrNull("expected");
        if (expected != null && !ANALYSIS_ID.matcher(expected).matches()) {
            throw invalid();
        }
        return new AnalysisRequest.PrepareItem(new Observation(
                identifier(observation.string("roundId"), MAX_ID_CODE_POINTS),
                identifier(observation.string("sourceId"), MAX_ID_CODE_POINTS),
                observation.count("page"),
                observation.count("ordinal"),
                match(observation.string("documentId"), DOCUMENT_ID),
                match(observation.string("rawVersion"), StrictJson.SHA256),
                match(observation.string("documentVersion"), StrictJson.SHA256)),
                kind, identifier(item.string("companyId"), MAX_ID_CODE_POINTS),
                new AnalysisRequest.GrantRef(identifier(grant.string("grantId"), MAX_GRANT_CODE_POINTS),
                        identifier(grant.string("revision"), MAX_GRANT_CODE_POINTS)),
                mode, sourceKind, expected);
    }

    private static AnalysisRequest.AdvanceItem advance(StrictJson.Obj item) {
        item.keys(Set.of("analysisId"), Set.of("recover"));
        boolean recover = item.has("recover") && item.bool("recover");
        return new AnalysisRequest.AdvanceItem(match(item.string("analysisId"), ANALYSIS_ID), recover);
    }

    /** 1 to {@code max} code points, well-formed and storable. */
    private static String identifier(String value, int max) {
        if (value.isEmpty() || Text.codePoints(value) > max || !Text.storable(value)) {
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

    private static AnalysisException invalid() {
        return new AnalysisException(AnalysisFailure.REQUEST_INVALID);
    }
}
