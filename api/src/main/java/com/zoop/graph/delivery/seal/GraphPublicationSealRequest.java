package com.zoop.graph.delivery.seal;

import java.util.Set;
import com.zoop.common.json.StrictJson;
import com.zoop.graph.delivery.GraphDeliveryException;
import com.zoop.graph.delivery.GraphDeliveryManifest;

public record GraphPublicationSealRequest(String graphVersionId, String expectedReceiptSha256, String destinationId,
        String operator) {
    public static final int MAX_BYTES = 64 * 1024;

    public GraphPublicationSealRequest {
        if (graphVersionId == null || !graphVersionId.matches("gv-[0-9a-f]{64}")
                || expectedReceiptSha256 == null || !StrictJson.SHA256.matcher(expectedReceiptSha256).matches()
                || !GraphDeliveryManifest.validDestination(destinationId)
                || operator == null || !operator.matches("[A-Za-z0-9][A-Za-z0-9._-]{0,63}")) {
            throw invalid();
        }
    }

    public static GraphPublicationSealRequest parse(byte[] bytes) {
        if (bytes == null || bytes.length == 0 || bytes.length > MAX_BYTES) throw invalid();
        try {
            var root = StrictJson.parseObject(bytes).exactly(Set.of("schemaVersion", "graphVersionId",
                    "expectedReceiptSha256", "destinationId", "operator"));
            if (!"zoop-graph-publication-seal-1".equals(root.string("schemaVersion"))) throw invalid();
            return new GraphPublicationSealRequest(root.string("graphVersionId"), root.string("expectedReceiptSha256"),
                    root.string("destinationId"), root.string("operator"));
        } catch (StrictJson.Malformed error) {
            throw invalid();
        }
    }

    private static GraphDeliveryException invalid() { return new GraphDeliveryException("request_invalid"); }
}
