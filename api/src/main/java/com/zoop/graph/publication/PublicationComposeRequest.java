package com.zoop.graph.publication;

import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.regex.Pattern;
import com.zoop.common.json.StrictJson;

public record PublicationComposeRequest(String baseVersionId, List<String> incomingVersionIds, String expectedActiveVersionId,
        String expectedBaseReceiptSha256, Map<String, String> incomingReceiptPins, long expectedRuleRevision,
        long expectedReviewRevision, String decisionsSha256, String operator) {
    public static final String SCHEMA = "zoop-graph-publication-compose-1";
    public static final int MAX_BYTES = 64 * 1024;
    private static final Pattern VERSION = Pattern.compile("gv-[0-9a-f]{64}");
    private static final Pattern ACTIVE_VERSION = Pattern.compile("[A-Za-z0-9._:-]{1,120}");
    private static final Pattern OPERATOR = Pattern.compile("[A-Za-z0-9][A-Za-z0-9._-]{0,63}");

    public PublicationComposeRequest {
        incomingVersionIds = List.copyOf(incomingVersionIds);
        incomingReceiptPins = Map.copyOf(incomingReceiptPins);
    }

    public static PublicationComposeRequest parse(byte[] bytes) {
        try {
            if (bytes.length == 0 || bytes.length > MAX_BYTES) throw invalid();
            var root = StrictJson.parseObject(bytes).exactly(Set.of("schemaVersion", "baseVersionId", "incomingVersionIds",
                    "expectedActiveVersionId", "expectedBaseReceiptSha256", "incomingReceiptPins", "expectedRuleRevision",
                    "expectedReviewRevision", "decisionsSha256", "operator"));
            if (!SCHEMA.equals(root.string("schemaVersion"))) throw invalid();
            String base = optional(root.stringOrNull("baseVersionId"), VERSION);
            String active = optional(root.stringOrNull("expectedActiveVersionId"), ACTIVE_VERSION);
            String basePin = optional(root.stringOrNull("expectedBaseReceiptSha256"), StrictJson.SHA256);
            if ((base == null) != (basePin == null)) throw invalid();
            List<String> incoming = root.strings("incomingVersionIds");
            if (incoming.isEmpty() || incoming.size() > 20 || !incoming.equals(incoming.stream().sorted().distinct().toList())) throw invalid();
            incoming.forEach(id -> required(id, VERSION));
            Map<String, String> pins = new TreeMap<>(); String previous = null;
            for (var pin : root.objects("incomingReceiptPins")) {
                pin.exactly(Set.of("versionId", "sha256")); String id = required(pin.string("versionId"), VERSION);
                if (previous != null && previous.compareTo(id) >= 0) throw invalid();
                previous = id; pins.put(id, required(pin.string("sha256"), StrictJson.SHA256));
            }
            if (!List.copyOf(pins.keySet()).equals(incoming)) throw invalid();
            return new PublicationComposeRequest(base, incoming, active, basePin, pins,
                    GraphPublicationReader.revision(root, "expectedRuleRevision"), GraphPublicationReader.revision(root, "expectedReviewRevision"),
                    required(root.string("decisionsSha256"), StrictJson.SHA256), required(root.string("operator"), OPERATOR));
        } catch (StrictJson.Malformed malformed) { throw invalid(); }
    }
    private static String optional(String value, Pattern pattern) { return value == null ? null : required(value, pattern); }
    private static String required(String value, Pattern pattern) { if (!pattern.matcher(value).matches()) throw invalid(); return value; }
    private static PublicationException invalid() { return new PublicationException("request_invalid"); }
}
