package com.zoop.graph.delivery.install;

import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.util.List;
import java.util.Objects;

import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.artifact.storage.ArtifactStoreException;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import com.zoop.document.evidence.service.GraphReceiptGrants;
import com.zoop.document.importer.SourceRegistry;
import com.zoop.document.repository.ArtifactRow;
import com.zoop.document.repository.DocumentRegistryRepository;
import com.zoop.graph.delivery.GraphDeliveryClosure;
import com.zoop.graph.delivery.GraphDeliveryException;
import com.zoop.graph.delivery.GraphDeliveryManifest;
import com.zoop.graph.delivery.JdbcGraphDeliveryStore;
import com.zoop.graph.delivery.JdbcGraphDeliveryStore.DestinationRow;
import com.zoop.graph.delivery.JdbcGraphDeliveryStore.InstallRow;
import com.zoop.graph.importer.GraphHandoffRepository;
import com.zoop.graph.version.GraphVersionRepository;
import com.zoop.graph.publication.GraphPublicationReader;
import com.zoop.graph.publication.GraphPublicationReader.Publication;
import com.zoop.graph.publication.PublicationException;
import org.springframework.dao.DataAccessException;
import org.springframework.transaction.support.TransactionOperations;

/** The serving-root lock spans independent closure/authority preflight, durable files and acknowledgement. */
public final class GraphDeliveryInstaller {
    private final ArtifactFileStore files;
    private final JdbcGraphDeliveryStore deliveries;
    private final DocumentRegistryRepository registry;
    private final GraphVersionRepository versions;
    private final GraphHandoffRepository graph;
    private final TransactionOperations transaction;
    private final Clock clock;
    private final GraphPublicationReader publications;

    public GraphDeliveryInstaller(ArtifactFileStore files, JdbcGraphDeliveryStore deliveries,
            DocumentRegistryRepository registry, GraphVersionRepository versions, GraphHandoffRepository graph,
            TransactionOperations transaction, Clock clock, GraphPublicationReader publications) {
        this.files = files;
        this.deliveries = deliveries;
        this.registry = registry;
        this.versions = versions;
        this.graph = graph;
        this.transaction = transaction;
        this.clock = clock;
        this.publications = publications;
    }

    String install(GraphDeliveryInstallSettings settings, Runnable schemaValidation) {
        try (ArtifactFileStore.Session session = files.open()) {
            schemaValidation.run();
            return transaction.execute(status -> installLocked(settings, session));
        } catch (ArtifactStoreException error) {
            throw new GraphDeliveryException(switch (error.reason()) {
                case BUSY -> "install_busy";
                case CONFLICT -> "target_conflict";
                case UNAVAILABLE -> "artifact_unavailable";
            });
        } catch (GraphReceiptGrants.Malformed | StrictJson.Malformed error) {
            throw new GraphDeliveryException("package_invalid");
        } catch (PublicationException error) {
            throw new GraphDeliveryException(error.code());
        } catch (SourceRegistry.Invalid error) {
            throw new GraphDeliveryException("source_authority_unavailable");
        } catch (DataAccessException error) {
            throw new GraphDeliveryException("database_unavailable");
        }
    }

    private String installLocked(GraphDeliveryInstallSettings settings, ArtifactFileStore.Session session) {
        deliveries.lockPackages();
        SourceRegistry sources = GraphDeliveryClosure.currentRegistry(settings.ingestionSources());
        var row = deliveries.findPackage(settings.versionId(), settings.destinationId())
                .orElseThrow(() -> new GraphDeliveryException("package_missing"));
        if (!row.packageDigest().equals(settings.expectedPackageDigest())) fail("package_conflict");
        GraphDeliveryManifest manifest = GraphDeliveryManifest.parse(row.manifest().getBytes(StandardCharsets.UTF_8));
        String packageDigest = manifest.digest();
        if (!packageDigest.equals(row.packageDigest()) || !manifest.versionId().equals(settings.versionId())
                || !manifest.destinationId().equals(settings.destinationId()) || !Objects.equals(manifest.handoffId(), row.handoffId())
                || !Objects.equals(manifest.manifestDigest(), row.manifestDigest()) || !Objects.equals(manifest.bundleDigest(), row.bundleDigest())
                || !Objects.equals(manifest.publicationId(), row.publicationId())
                || !Objects.equals(manifest.publicationReceiptSha256(), row.publicationReceiptSha256())
                || manifest.files().size() != row.fileCount() || manifest.totalBytes() != row.totalBytes()) fail("package_invalid");
        List<ArtifactRow> rows = manifest.files().stream().map(pin -> {
            ArtifactRow artifact = registry.findArtifact(pin.artifactId())
                    .orElseThrow(() -> new GraphDeliveryException("package_invalid"));
            if (!pin.equals(GraphDeliveryManifest.FilePin.from(artifact))) fail("package_invalid");
            return artifact;
        }).toList();
        settings.limits().checkPackage(rows);
        ArtifactRow receipt = rows.stream().filter(file -> file.id().equals("artifact-receipt-" + settings.versionId()))
                .findFirst().orElseThrow(() -> new GraphDeliveryException("package_invalid"));
        byte[] receiptBytes = deliveries.readContent(receipt);
        Publication publication = manifest.composed() ? publications.read(settings.versionId()) : null;
        List<ArtifactRow> closure = publication == null
                ? GraphDeliveryClosure.resolve(settings.versionId(), receiptBytes, registry, versions, graph)
                : GraphDeliveryClosure.resolve(publication, publications, manifest.publicationReceiptSha256());
        if (!manifest.files().equals(closure.stream().map(GraphDeliveryManifest.FilePin::from).toList())) fail("package_invalid");
        StrictJson.Obj bundle = null;
        if (publication == null) {
            bundle = GraphReceiptGrants.bundle(receiptBytes, settings.versionId());
            StrictJson.Obj receiptDocument = StrictJson.parseObject(receiptBytes);
            if (!receiptDocument.string("handoffId").equals(manifest.handoffId())
                    || !receiptDocument.string("manifestDigest").equals(manifest.manifestDigest())
                    || !receiptDocument.string("bundleDigest").equals(manifest.bundleDigest())) fail("package_invalid");
        } else if (!publication.publicationId().equals(manifest.publicationId())) {
            fail("package_invalid");
        }
        requireRights(publication, bundle, sources);

        byte[] marker = marker(settings);
        String markerUri = ArtifactFileStore.URI_SCHEME + "graph_delivery/destination-" + settings.destinationId() + ".json";
        String markerDigest = Canonical.sha256(marker);
        boolean markerPresent;
        try {
            markerPresent = session.preflight(markerUri, markerDigest, marker.length);
        } catch (ArtifactStoreException error) {
            throw new GraphDeliveryException("destination_root_mismatch");
        }
        var destination = deliveries.findDestination(settings.destinationId());
        if (destination.isPresent() && (!markerPresent || !destination.get().markerSha256().equals(markerDigest)
                || destination.get().markerBytes() != marker.length)) fail("destination_root_mismatch");
        var installed = deliveries.findInstall(settings.versionId(), settings.destinationId());
        if (installed.isPresent() && (!installed.get().packageDigest().equals(packageDigest) || destination.isEmpty())) {
            fail("package_invalid");
        }
        for (ArtifactRow artifact : rows) {
            if (!artifact.id().equals(receipt.id())) deliveries.readContent(artifact);
            boolean present = session.preflight(artifact.storageUri(), artifact.sha256(), artifact.bytes());
            if (installed.isPresent() && !present) fail("target_conflict");
        }
        sources.checkRoutingUnchanged();
        requireRights(publication, bundle, GraphDeliveryClosure.currentRegistry(settings.ingestionSources()));
        sources.checkRoutingUnchanged();
        if (installed.isPresent()) return "already_installed";

        // A late I/O failure or revocation can leave durable files; the transaction then withholds acknowledgement.
        session.put("graph_delivery", "destination-" + settings.destinationId() + ".json", marker);
        if (destination.isEmpty()) {
            deliveries.insertDestination(new DestinationRow(settings.destinationId(), markerDigest, marker.length, clock.instant()));
        }
        for (ArtifactRow artifact : rows) {
            String relative = artifact.storageUri().substring(ArtifactFileStore.URI_SCHEME.length());
            int separator = relative.indexOf('/');
            session.put(relative.substring(0, separator), relative.substring(separator + 1), deliveries.readContent(artifact));
        }
        sources.checkRoutingUnchanged();
        requireRights(publication, bundle, GraphDeliveryClosure.currentRegistry(settings.ingestionSources()));
        sources.checkRoutingUnchanged();
        deliveries.insertInstall(new InstallRow(settings.versionId(), settings.destinationId(), packageDigest, clock.instant()));
        return "installed";
    }

    private void requireRights(Publication publication, StrictJson.Obj bundle, SourceRegistry sources) {
        if (publication == null) requireRights(bundle, sources);
        else GraphDeliveryClosure.requireRights(publication, registry, sources, clock);
    }

    private void requireRights(StrictJson.Obj bundle, SourceRegistry sources) {
        try {
            for (StrictJson.Obj item : bundle.objects("articles")) {
                String articleId = item.string("articleId");
                var article = registry.lockArticle(articleId).orElseThrow(() -> new GraphDeliveryException("rights_denied"));
                if (!"available".equals(article.accessStatus())) fail("rights_denied");
                for (var pin : GraphReceiptGrants.pins(bundle, articleId, item.string("articleVersion"))) {
                    if (!pin.sourceId().equals(article.provider())
                            || sources.denial(pin.sourceId(), pin.grantId(), pin.revision(), clock.instant()) != null) fail("rights_denied");
                }
            }
        } catch (SourceRegistry.Invalid error) {
            throw new GraphDeliveryException("source_authority_unavailable");
        }
    }


    static byte[] marker(GraphDeliveryInstallSettings settings) {
        var value = StrictJson.newObject();
        value.put("schemaVersion", "zoop-graph-delivery-destination-1");
        value.put("destinationId", settings.destinationId());
        value.put("rootDigest", Canonical.sha256(settings.artifactRoot().toString()));
        return Canonical.bytes(value);
    }

    private static void fail(String code) { throw new GraphDeliveryException(code); }
}
