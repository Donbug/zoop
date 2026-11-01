package com.zoop.graph.importer;

import java.nio.file.Files;
import java.nio.file.Path;

import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import com.zoop.document.importer.Observation;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class HandoffSourceContextsTest {
    @TempDir Path temp;

    private ObjectNode inventory(HandoffFixtures.Built built) throws Exception {
        Path root = temp.toRealPath();
        ObjectNode document = StrictJson.newObject().put("schemaVersion", HandoffSourceContexts.SCHEMA);
        ObjectNode context = document.putArray("contexts").addObject().put("contextId", "one");
        context.put("relationStateDirectory", Files.createDirectory(root.resolve("relation")).toString());
        context.put("extractionStateDirectory", Files.createDirectory(root.resolve("extraction")).toString());
        context.put("ingestionStateDirectory", Files.createDirectory(root.resolve("ingestion")).toString());
        context.put("sources", Files.writeString(root.resolve("sources.json"), "{}").toString());
        context.set("sourcePins", built.manifest().get("sources").deepCopy());
        Observation ref = HandoffFixtures.SELECTOR;
        context.putArray("observations").addObject().put("roundId", ref.roundId()).put("sourceId", ref.sourceId())
                .put("page", ref.page()).put("ordinal", ref.ordinal()).put("documentId", ref.documentId())
                .put("rawVersion", ref.rawVersion()).put("documentVersion", ref.documentVersion());
        return document;
    }

    private HandoffSourceContexts read(ObjectNode inventory) throws Exception {
        byte[] bytes = StrictJson.write(inventory);
        Path file = Files.write(temp.toRealPath().resolve("contexts.json"), bytes);
        return HandoffSourceContexts.read(file, Canonical.sha256(bytes));
    }

    @Test
    void exactPinsAndAllSevenObservationFieldsAreRequiredForTheVerifiedBundle() throws Exception {
        var built = HandoffFixtures.build();
        var bundle = new HandoffExportParser().parse(built.envelopeBytes(), built.request()).bundle();
        ObjectNode document = inventory(built);
        var contexts = read(document);
        contexts.selected(bundle);
        var ref = HandoffFixtures.SELECTOR;
        assertThrows(GraphHandoffException.class, () -> contexts.observation(new Observation(ref.roundId(), ref.sourceId(),
                ref.page(), ref.ordinal() + 1, ref.documentId(), ref.rawVersion(), ref.documentVersion())));
        ObjectNode pin = (ObjectNode) document.path("contexts").get(0).path("sourcePins").get(0);
        pin.put("reviewDigest", "f".repeat(64));
        var misrouted = read(document);
        assertThrows(GraphHandoffException.class, () -> misrouted.selected(bundle));
        assertThrows(GraphHandoffException.class, () -> contexts.selected(bundle));
    }

    @Test
    void duplicateRoutesAndNestedInventoriesAreRejectedBeforeAnyExporterRuns() throws Exception {
        ObjectNode document = inventory(HandoffFixtures.build());
        ArrayNode contexts = (ArrayNode) document.get("contexts");
        contexts.add(contexts.get(0).deepCopy());
        assertThrows(GraphHandoffImportConfigurationException.class, () -> read(document));
        contexts.remove(1);
        ObjectNode context = (ObjectNode) contexts.get(0);
        ArrayNode observations = (ArrayNode) context.get("observations");
        observations.add(observations.get(0).deepCopy());
        assertThrows(GraphHandoffImportConfigurationException.class, () -> read(document));
        observations.remove(1);
        context.put("sourceContexts", "/nested.json");
        assertThrows(GraphHandoffImportConfigurationException.class, () -> read(document));
    }

    @Test
    void inventoryMayExceedTwentyWhileTheSelectedNativeManifestMayNot() throws Exception {
        var built = HandoffFixtures.build();
        ObjectNode document = inventory(built);
        ArrayNode routes = (ArrayNode) document.path("contexts").get(0).path("sourcePins");
        ObjectNode original = (ObjectNode) routes.get(0).deepCopy();
        for (int i = routes.size(); i < 25; i++) {
            ObjectNode pin = original.deepCopy();
            ((ObjectNode) pin.get("relation")).put("jobId", "extra-" + i);
            routes.add(pin);
        }
        var contexts = read(document);
        contexts.selected(new HandoffExportParser().parse(built.envelopeBytes(), built.request()).bundle());
        ObjectNode manifest = built.manifest().deepCopy();
        ArrayNode selected = manifest.putArray("sources");
        for (int i = 0; i < 20; i++) selected.add(routes.get(i).deepCopy());
        assertEquals(20, HandoffBundleVerifier.verifyManifest(manifest).sources().size());
        selected.add(routes.get(20).deepCopy());
        assertThrows(StrictJson.Malformed.class, () -> HandoffBundleVerifier.verifyManifest(manifest));
    }
}
