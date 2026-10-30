package com.zoop.graph.importer;

import java.util.Set;
import java.util.regex.Pattern;

import com.zoop.ai.http.HandoffWire;
import com.zoop.common.json.StrictJson;

/**
 * Parses the operator request ({@code zoop-graph-handoff-import-1}). The schema is closed: an unknown or duplicate key, a
 * wrong type, a malformed value or an oversized file is {@code request_invalid}. Both digest pins are required, so a request can
 * never mean "import whatever the handoff currently is". There is deliberately no key through which a bundle, a path, a grant or
 * an activation could be supplied.
 */
public final class GraphHandoffRequestParser {
    public static final String SCHEMA_VERSION = "zoop-graph-handoff-import-1";
    public static final int MAX_BYTES = 64 * 1024;

    private static final Pattern HANDOFF_ID = HandoffWire.HANDOFF_ID;
    private static final Pattern OPERATOR = Pattern.compile("[A-Za-z0-9][A-Za-z0-9._-]{0,63}");

    public GraphHandoffRequest parse(byte[] bytes) {
        if (bytes.length == 0 || bytes.length > MAX_BYTES) {
            throw invalid();
        }
        try {
            StrictJson.Obj root = StrictJson.parseObject(bytes).exactly(
                    Set.of("schemaVersion", "handoffId", "expectedManifestDigest", "expectedBundleDigest", "operator"));
            if (!SCHEMA_VERSION.equals(root.string("schemaVersion"))) {
                throw invalid();
            }
            return new GraphHandoffRequest(
                    match(root.string("handoffId"), HANDOFF_ID),
                    match(root.string("expectedManifestDigest"), StrictJson.SHA256),
                    match(root.string("expectedBundleDigest"), StrictJson.SHA256),
                    match(root.string("operator"), OPERATOR));
        } catch (StrictJson.Malformed malformed) {
            throw invalid();
        }
    }

    private static String match(String value, Pattern pattern) {
        if (!pattern.matcher(value).matches()) {
            throw invalid();
        }
        return value;
    }

    private static GraphHandoffException invalid() {
        return new GraphHandoffException(GraphHandoffFailure.REQUEST_INVALID);
    }
}
