package com.zoop.graph.delivery;

import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.List;
import java.util.stream.IntStream;
import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import com.zoop.document.repository.ArtifactRow;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.node.ObjectNode;
import static org.junit.jupiter.api.Assertions.*;

class GraphDeliveryManifestTest {
    private static final String HANDOFF = "synthetic-delivery";
    private static final String VERSION = "gv-" + Canonical.sha256(HANDOFF);
    private static final String HASH = "a".repeat(64);

    private static ArtifactRow row(String id, String kind, long bytes) {
        String directory = kind.equals("graph_bundle_snapshot") ? "graph_bundle" : kind;
        return new ArtifactRow(id, kind, "artifact-root:" + directory + "/" + id + ".json", HASH, bytes,
                "application/json", Instant.EPOCH);
    }

    private static GraphDeliveryManifest manifest() {
        return GraphDeliveryManifest.build(VERSION, "serving-a", HANDOFF, HASH, "b".repeat(64),
                List.of(row("z-receipt", "verification_receipt", 7), row("a-snapshot", "graph_snapshot", 11)));
    }

    @Test void canonicalIdentityIsOrderIndependentAndDestinationPinned() {
        var value = manifest();
        assertEquals("a-snapshot", value.files().getFirst().artifactId());
        assertEquals(18, value.totalBytes());
        assertEquals(value, GraphDeliveryManifest.parse(value.bytes()));
        assertEquals(Canonical.sha256(value.bytes()), value.digest());
        var reversed = GraphDeliveryManifest.build(VERSION, "serving-a", HANDOFF, HASH, "b".repeat(64),
                List.of(row("a-snapshot", "graph_snapshot", 11), row("z-receipt", "verification_receipt", 7)));
        assertEquals(value.digest(), reversed.digest());
        assertNotEquals(value.digest(), GraphDeliveryManifest.build(VERSION, "serving-b", HANDOFF, HASH, "b".repeat(64),
                List.of(row("a-snapshot", "graph_snapshot", 11), row("z-receipt", "verification_receipt", 7))).digest());
    }

    @Test void closedSchemaAndCanonicalBytesRejectEarlierSchemaAndWrongPins() {
        for (String key : List.of("extra", "schemaVersion", "versionId")) {
            ObjectNode changed = (ObjectNode) StrictJson.parseObject(manifest().bytes()).node();
            changed.put(key, key.equals("schemaVersion") ? "zoop-graph-delivery-package-1" : "wrong");
            assertInvalid(Canonical.bytes(changed));
        }
        assertInvalid((new String(manifest().bytes(), StandardCharsets.UTF_8) + "\n").getBytes(StandardCharsets.UTF_8));
        assertInvalid("{\"schemaVersion\":1,\"schemaVersion\":2}".getBytes(StandardCharsets.UTF_8));
        ObjectNode swapped = (ObjectNode) StrictJson.parseObject(manifest().bytes()).node();
        ((ObjectNode) swapped.get("files").get(0)).put("storageUri", "artifact-root:extracted_text/a-snapshot.json");
        assertInvalid(Canonical.bytes(swapped));
    }

    @Test void fourKindsUseTheirExactDirectoriesAndSafeUniqueLeaves() {
        var rows = List.of(row("snapshot", "graph_snapshot", 1), row("receipt", "verification_receipt", 1),
                row("projection", "graph_bundle_snapshot", 1), row("text", "extracted_text", 1));
        var value = GraphDeliveryManifest.build(VERSION, "serving-a", HANDOFF, HASH, HASH, rows);
        assertEquals(value, GraphDeliveryManifest.parse(value.bytes()));
        assertEquals("artifact-root:graph_bundle/projection.json", value.files().getFirst().storageUri());
        for (String uri : List.of("artifact-root:graph_bundle_snapshot/projection.json", "artifact-root:graph_bundle/../x.json",
                "artifact-root:graph_bundle/a/b.json", "file:/tmp/x.json", "artifact-root:graph_bundle/.hidden.json")) {
            assertThrows(GraphDeliveryException.class, () -> new GraphDeliveryManifest.FilePin("projection", "graph_bundle_snapshot",
                    uri, HASH, 1, "application/json"));
        }
        assertThrows(GraphDeliveryException.class, () -> GraphDeliveryManifest.build(VERSION, "serving-a", HANDOFF, HASH, HASH,
                List.of(row("same", "graph_snapshot", 1), row("same", "verification_receipt", 2))));
    }

    @Test void fileCountFileBytesPackageAndPendingBoundsAreInclusive() {
        List<ArtifactRow> rows = IntStream.range(0, 1003).mapToObj(i -> row("text-" + i, "extracted_text", 1)).toList();
        var limits = new GraphDeliveryLimits(1003, 1003, 2006);
        assertDoesNotThrow(() -> limits.checkPackage(rows));
        assertEquals(1003, GraphDeliveryManifest.parse(GraphDeliveryManifest.build(VERSION, "serving-a", HANDOFF, HASH, HASH, rows).bytes()).files().size());
        assertThrows(GraphDeliveryException.class, () -> new GraphDeliveryLimits(1004, 1004, 2008));
        assertThrows(GraphDeliveryException.class, () -> limits.checkPackage(IntStream.range(0, 1004)
                .mapToObj(i -> row("text-" + i, "extracted_text", 1)).toList()));
        assertDoesNotThrow(() -> GraphDeliveryManifest.FilePin.from(row("maximum", "extracted_text", ArtifactFileStore.MAX_READ_BYTES)));
        assertThrows(GraphDeliveryException.class, () -> GraphDeliveryManifest.FilePin.from(row("big", "extracted_text", ArtifactFileStore.MAX_READ_BYTES + 1)));
        assertThrows(GraphDeliveryException.class, () -> new GraphDeliveryLimits(1003, 1002, 2006).checkPackage(rows));
        assertDoesNotThrow(() -> limits.checkPending(1003, 1003));
        assertEquals("outbox_full", assertThrows(GraphDeliveryException.class, () -> limits.checkPending(1004, 1003)).code());
        assertThrows(GraphDeliveryException.class, () -> limits.checkPending(Long.MAX_VALUE, 1));
        assertThrows(GraphDeliveryException.class, () -> limits.checkPackage(List.of(row("x", "extracted_text", Long.MAX_VALUE))));
    }

    @Test void publicationManifestHasOnlyPublicationPinsAndKeepsNativeBytes() {
        String publication = "publication:" + HASH;
        String version = "gv-" + Canonical.sha256(publication);
        var rows = List.of(row("snapshot", "graph_snapshot", 1), row("receipt", "verification_receipt", 2),
                row("original", "verification_receipt", 3), row("projection", "graph_bundle_snapshot", 4));
        var value = GraphDeliveryManifest.publication(version, "serving-a", publication, HASH, rows);
        assertEquals(value, GraphDeliveryManifest.parse(value.bytes()));
        var document = StrictJson.parseObject(value.bytes()).exactly(java.util.Set.of("schemaVersion", "versionId",
                "destinationId", "publicationId", "publicationReceiptSha256", "files"));
        assertEquals(GraphDeliveryManifest.PUBLICATION_SCHEMA, document.string("schemaVersion"));
        assertNull(value.handoffId());
        assertNull(value.manifestDigest());
        assertNull(value.bundleDigest());
        assertEquals("""
                {"bundleDigest":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","destinationId":"serving-a","files":[{"artifactId":"a-snapshot","bytes":11,"kind":"graph_snapshot","mediaType":"application/json","sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","storageUri":"artifact-root:graph_snapshot/a-snapshot.json"},{"artifactId":"z-receipt","bytes":7,"kind":"verification_receipt","mediaType":"application/json","sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","storageUri":"artifact-root:verification_receipt/z-receipt.json"}],"handoffId":"synthetic-delivery","manifestDigest":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","schemaVersion":"zoop-graph-delivery-package-2","versionId":"%s"}""".formatted(VERSION),
                new String(manifest().bytes(), StandardCharsets.UTF_8));
        for (String field : List.of("handoffId", "manifestDigest", "bundleDigest", "extra")) {
            ObjectNode mixed = (ObjectNode) StrictJson.parseObject(value.bytes()).node();
            mixed.put(field, HASH);
            assertInvalid(Canonical.bytes(mixed));
        }
        ObjectNode missing = (ObjectNode) StrictJson.parseObject(value.bytes()).node();
        missing.remove("publicationReceiptSha256");
        assertInvalid(Canonical.bytes(missing));
        assertThrows(GraphDeliveryException.class, () -> GraphDeliveryManifest.publication(VERSION, "serving-a", publication, HASH, rows));
    }

    @Test void publicationFileBoundsDoNotImposeTwentyLeafLimit() {
        var rows = IntStream.range(0, 62).mapToObj(i -> row("leaf-" + i, "verification_receipt", 1)).toList();
        String publication = "publication:" + HASH;
        assertEquals(62, GraphDeliveryManifest.publication("gv-" + Canonical.sha256(publication), "serving-a",
                publication, HASH, rows).files().size());
    }

    private static void assertInvalid(byte[] bytes) {
        assertEquals("package_invalid", assertThrows(GraphDeliveryException.class, () -> GraphDeliveryManifest.parse(bytes)).code());
    }
}
