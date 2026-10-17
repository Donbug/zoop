package com.zoop.graph.read;

import com.zoop.graph.snapshot.GraphSnapshotCodec;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import java.io.IOException;
import java.io.InputStream;
import java.io.UncheckedIOException;

final class GraphReadFixtures {
    static final String NVDA = "NASDAQ:NVDA";
    static final String HYNIX = "KRX:000660";
    static final String HANMI = "KRX:042700";
    static final String HBM_SUPPLY = "iss-fixture-hbm-supply";
    static final String HBM_EQUIP = "iss-fixture-hbm-equip";
    static final String AI_ACCEL = "iss-fixture-ai-accel";

    private GraphReadFixtures() {
    }

    static byte[] bytes(String versionId) {
        try (InputStream in = GraphReadFixtures.class.getClassLoader()
                .getResourceAsStream("graph-fixtures/" + versionId + ".json")) {
            return in.readAllBytes();
        } catch (IOException exception) {
            throw new UncheckedIOException(exception);
        }
    }

    static PublicGraphSnapshot snapshot(String versionId) {
        return GraphSnapshotCodec.read(bytes(versionId), versionId);
    }
}
