package com.zoop.graph.delivery;

import java.util.HashSet;
import java.nio.file.Path;
import java.time.Clock;
import java.util.List;
import java.util.Set;
import java.util.TreeMap;

import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import com.zoop.document.evidence.service.GraphReceiptGrants;
import com.zoop.document.repository.ArtifactRow;
import com.zoop.document.repository.DocumentRegistryRepository;
import com.zoop.document.importer.SourceRegistry;
import com.zoop.graph.publication.GraphPublicationAuthority;
import com.zoop.graph.publication.GraphPublicationReader;
import com.zoop.graph.publication.GraphPublicationReader.Publication;
import com.zoop.graph.importer.GraphHandoffRepository;
import com.zoop.graph.version.GraphVersionRepository;

/** The full receipt and registered composition determine delivery, including publication-filtered article texts. */
public final class GraphDeliveryClosure {
    private GraphDeliveryClosure() { }

    public static List<ArtifactRow> resolve(String versionId, byte[] receiptBytes, DocumentRegistryRepository registry,
            GraphVersionRepository versions, GraphHandoffRepository graph) {
        try {
            var version = versions.find(versionId).orElseThrow(GraphDeliveryClosure::invalid);
            if (!"snapshot".equals(version.kind())) throw invalid();
            TreeMap<String, ArtifactRow> rows = new TreeMap<>();
            ArtifactRow snapshot = artifact(registry, version.snapshotArtifactId(), "graph_snapshot");
            if (!snapshot.storageUri().equals(version.snapshotStorageUri()) || !snapshot.sha256().equals(version.snapshotSha256())) {
                throw invalid();
            }
            include(rows, snapshot);
            ArtifactRow receipt = artifact(registry, "artifact-receipt-" + versionId, "verification_receipt");
            if (receiptBytes.length != receipt.bytes() || !Canonical.sha256(receiptBytes).equals(receipt.sha256())) throw invalid();
            include(rows, receipt);
            StrictJson.Obj root = StrictJson.parseObject(receiptBytes).exactly(Set.of("schemaVersion", "handoffId",
                    "manifestDigest", "bundleDigest", "contentDigest", "manifest", "bundle", "producer", "appVerification"));
            if (!"zoop-graph-handoff-import-receipt-1".equals(root.string("schemaVersion"))) throw invalid();
            StrictJson.Obj bundle = GraphReceiptGrants.bundle(receiptBytes, versionId);
            StrictJson.Obj manifest = root.object("manifest");
            String schema = bundle.string("schemaVersion");
            String policy = switch (schema) {
                case "zoop-graph-handoff-bundle-8" -> "zoop-public-projection-policy-2";
                case "zoop-graph-handoff-bundle-9" -> "zoop-public-projection-policy-3";
                default -> throw invalid();
            };
            if (!"zoop-ai-handoff-1".equals(manifest.string("schemaVersion"))
                    || !policy.equals(bundle.object("policy").string("version"))
                    || !policy.equals(manifest.string("policyVersion"))
                    || !Canonical.digest(manifest.node()).equals(root.string("manifestDigest"))
                    || !Canonical.digest(bundle.node()).equals(root.string("bundleDigest"))
                    || !root.string("handoffId").equals(bundle.string("handoffId"))
                    || !root.string("handoffId").equals(manifest.string("handoffId"))
                    || !root.string("manifestDigest").equals(bundle.string("manifestDigest"))) throw invalid();
            var sources = graph.sources(versionId);
            if (sources.size() != 1) throw invalid();
            var source = sources.getFirst();
            if (source.ordinal() != 0 || !root.string("handoffId").equals(source.handoffId())
                    || !receipt.id().equals(source.receiptArtifactId()) || source.bundleSnapshotArtifactId() == null) throw invalid();
            include(rows, artifact(registry, source.bundleSnapshotArtifactId(),
                    snapshot.id().equals(source.bundleSnapshotArtifactId()) ? "graph_snapshot" : "graph_bundle_snapshot"));
            Set<String> articles = new HashSet<>();
            for (StrictJson.Obj article : bundle.objects("articles")) {
                String articleId = article.string("articleId");
                String articleVersion = article.string("articleVersion");
                if (!articles.add(articleId + "\n" + articleVersion)) throw invalid();
                GraphReceiptGrants.pins(bundle, articleId, articleVersion);
                var registered = registry.findVersion(articleId, articleVersion).orElseThrow(GraphDeliveryClosure::invalid);
                ArtifactRow text = artifact(registry, registered.textArtifactId(), "extracted_text");
                if (!article.string("textSha256").equals(text.sha256())) throw invalid();
                include(rows, text);
            }
            return List.copyOf(rows.values());
        } catch (StrictJson.Malformed | GraphReceiptGrants.Malformed invalid) {
            throw invalid();
        }
    }

    public static List<ArtifactRow> resolve(Publication publication, GraphPublicationReader reader,
            String expectedReceiptSha256) {
        if (!publication.composed() || !publication.receipt().sha256().equals(expectedReceiptSha256)) throw invalid();
        List<ArtifactRow> closure = reader.closure(publication);
        for (ArtifactRow row : closure) GraphDeliveryManifest.FilePin.from(row);
        return closure;
    }

    public static SourceRegistry currentRegistry(String value) {
        if (value == null || value.isBlank()) throw new GraphDeliveryException("source_authority_unavailable");
        try {
            Path path = Path.of(value);
            if (!path.isAbsolute() || !path.equals(path.normalize())) throw new GraphDeliveryException("source_authority_unavailable");
            return SourceRegistry.read(path);
        } catch (SourceRegistry.Invalid | java.nio.file.InvalidPathException error) {
            throw new GraphDeliveryException("source_authority_unavailable");
        }
    }

    public static void requireRights(Publication publication, DocumentRegistryRepository registry,
            SourceRegistry sources, Clock clock) {
        publication.contributions().stream().flatMap(source -> source.projection().articles().stream())
                .map(article -> article.articleId()).distinct().sorted().forEach(id -> {
                    var article = registry.lockArticle(id).orElseThrow(() -> new GraphDeliveryException("rights_denied"));
                    if (!"available".equals(article.accessStatus())) throw new GraphDeliveryException("rights_denied");
                });
        GraphPublicationAuthority.requireFullRights(publication, registry, sources, clock.instant());
    }

    private static void include(TreeMap<String, ArtifactRow> rows, ArtifactRow row) {
        ArtifactRow previous = rows.putIfAbsent(row.id(), row);
        if (previous != null && !previous.equals(row)) throw invalid();
    }

    private static ArtifactRow artifact(DocumentRegistryRepository registry, String id, String kind) {
        if (id == null) throw invalid();
        ArtifactRow row = registry.findArtifact(id).orElseThrow(GraphDeliveryClosure::invalid);
        if (!kind.equals(row.kind())) throw invalid();
        if (row.bytes() > ArtifactFileStore.MAX_READ_BYTES) throw new GraphDeliveryException("package_too_large");
        GraphDeliveryManifest.FilePin.from(row);
        return row;
    }

    private static GraphDeliveryException invalid() { return new GraphDeliveryException("package_invalid"); }
}
