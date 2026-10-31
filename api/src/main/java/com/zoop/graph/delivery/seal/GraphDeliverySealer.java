package com.zoop.graph.delivery.seal;

import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.util.List;
import java.util.Objects;

import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.artifact.storage.ArtifactStoreException;
import com.zoop.common.json.Canonical;
import com.zoop.document.repository.ArtifactRow;
import com.zoop.document.repository.DocumentRegistryRepository;
import com.zoop.document.importer.SourceRegistry;
import com.zoop.graph.delivery.GraphDeliveryClosure;
import com.zoop.graph.delivery.GraphDeliveryException;
import com.zoop.graph.delivery.GraphDeliveryLimits;
import com.zoop.graph.delivery.GraphDeliveryManifest;
import com.zoop.graph.delivery.JdbcGraphDeliveryStore;
import com.zoop.graph.delivery.JdbcGraphDeliveryStore.PackageRow;
import com.zoop.graph.importer.GraphHandoffException;
import com.zoop.graph.importer.GraphHandoffImporter;
import com.zoop.graph.importer.GraphHandoffRepository;
import com.zoop.graph.importer.GraphHandoffRequest;
import com.zoop.graph.importer.GraphHandoffResult;
import com.zoop.graph.version.GraphVersionRepository;
import com.zoop.graph.publication.GraphPublicationReader;
import com.zoop.graph.publication.PublicationException;
import org.springframework.transaction.support.TransactionOperations;

/** Staging commits first; the complete outbox commits separately under the same producer-root lock. */
public final class GraphDeliverySealer {
    public record Sealed(String outcome, String versionId, String destinationId, String packageDigest, int fileCount,
            long totalBytes) { }

    private final ArtifactFileStore files;
    private final DocumentRegistryRepository registry;
    private final GraphVersionRepository versions;
    private final GraphHandoffRepository graph;
    private final JdbcGraphDeliveryStore deliveries;
    private final GraphHandoffImporter importer;
    private final TransactionOperations transaction;
    private final Clock clock;
    private final GraphPublicationReader publications;
    private final String ingestionSources;

    public GraphDeliverySealer(ArtifactFileStore files, DocumentRegistryRepository registry, GraphVersionRepository versions,
            GraphHandoffRepository graph, JdbcGraphDeliveryStore deliveries, GraphHandoffImporter importer,
            TransactionOperations transaction, Clock clock, GraphPublicationReader publications, String ingestionSources) {
        this.files = files;
        this.registry = registry;
        this.versions = versions;
        this.graph = graph;
        this.deliveries = deliveries;
        this.importer = importer;
        this.transaction = transaction;
        this.clock = clock;
        this.publications = publications;
        this.ingestionSources = ingestionSources;
    }

    public Sealed seal(GraphHandoffRequest request, String destination, GraphDeliveryLimits limits) {
        String version = "gv-" + Canonical.sha256(request.handoffId());
        try (ArtifactFileStore.Session session = files.open()) {
            var previous = deliveries.findPackage(version, destination);
            if (previous.isPresent()) {
                PackageRow row = previous.get();
                requirePins(row, request);
                byte[] receipt = receipt(version, session);
                List<ArtifactRow> closure = GraphDeliveryClosure.resolve(version, receipt, registry, versions, graph);
                GraphDeliveryManifest manifest = manifest(version, destination, request, closure);
                requireSame(row, manifest);
                // Receipt reconciliation is read-only and does not certify fresh source authority.
                verifyFiles(session, closure);
                return result("already_sealed", manifest);
            }
            GraphHandoffResult imported = importer.run(session, request);
            if (!imported.succeeded()) throw new GraphDeliveryException(imported.failure().failure().code());
            if (imported.staged().outcome() != GraphHandoffResult.Outcome.STAGED
                    && imported.staged().outcome() != GraphHandoffResult.Outcome.UNCHANGED) {
                throw new GraphDeliveryException("import_failed");
            }
            return transaction.execute(status -> {
                deliveries.lockPackages();
                byte[] receipt = receipt(version, session);
                List<ArtifactRow> closure = GraphDeliveryClosure.resolve(version, receipt, registry, versions, graph);
                GraphDeliveryManifest manifest = manifest(version, destination, request, closure);
                var raced = deliveries.findPackage(version, destination);
                if (raced.isPresent()) {
                    requireSame(raced.get(), manifest);
                    verifyFiles(session, closure);
                    return result("already_sealed", manifest);
                }
                limits.checkPackage(closure);
                limits.checkPending(deliveries.pendingBytes(destination), manifest.totalBytes());
                for (ArtifactRow artifact : closure) {
                    byte[] content = artifact.id().equals("artifact-receipt-" + version) ? receipt
                            : session.read(artifact.storageUri(), artifact.sha256(), artifact.bytes());
                    deliveries.putContent(artifact, new ByteArrayInputStream(content), content.length);
                }
                byte[] bytes = manifest.bytes();
                deliveries.insertPackage(new PackageRow(version, destination, request.handoffId(), request.expectedManifestDigest(),
                        request.expectedBundleDigest(), null, null, new String(bytes, StandardCharsets.UTF_8), Canonical.sha256(bytes),
                        closure.size(), manifest.totalBytes(), request.operator(), clock.instant()));
                importer.revalidateCurrent(request, receipt);
                return result("sealed", manifest);
            });
        } catch (ArtifactStoreException refused) {
            throw new GraphDeliveryException(refused.reason() == ArtifactStoreException.Reason.BUSY ? "import_busy"
                    : refused.reason() == ArtifactStoreException.Reason.CONFLICT ? "artifact_file_conflict" : "artifact_store_unavailable");
        } catch (GraphHandoffException refused) {
            throw new GraphDeliveryException(refused.failure().code());
        }
    }

    public Sealed sealPublication(GraphPublicationSealRequest request, GraphDeliveryLimits limits) {
        try (ArtifactFileStore.Session session = files.open()) {
            return transaction.execute(status -> {
                deliveries.lockPackages();
                var publication = publications.read(request.graphVersionId());
                List<ArtifactRow> closure = GraphDeliveryClosure.resolve(publication, publications, request.expectedReceiptSha256());
                GraphDeliveryManifest manifest = GraphDeliveryManifest.publication(publication.versionId(), request.destinationId(),
                        publication.publicationId(), publication.receipt().sha256(), closure);
                SourceRegistry sources = GraphDeliveryClosure.currentRegistry(ingestionSources);
                GraphDeliveryClosure.requireRights(publication, registry, sources, clock);
                var previous = deliveries.findPackage(publication.versionId(), request.destinationId());
                if (previous.isPresent()) {
                    requireSame(previous.get(), manifest);
                    verifyFiles(session, closure);
                    sources.checkRoutingUnchanged();
                    GraphDeliveryClosure.requireRights(publication, registry, GraphDeliveryClosure.currentRegistry(ingestionSources), clock);
                    sources.checkRoutingUnchanged();
                    return result("already_sealed", manifest);
                }
                limits.checkPackage(closure);
                limits.checkPending(deliveries.pendingBytes(request.destinationId()), manifest.totalBytes());
                for (ArtifactRow artifact : closure) {
                    byte[] content = session.read(artifact.storageUri(), artifact.sha256(), artifact.bytes());
                    deliveries.putContent(artifact, new ByteArrayInputStream(content), content.length);
                }
                byte[] bytes = manifest.bytes();
                deliveries.insertPackage(new PackageRow(publication.versionId(), request.destinationId(), null, null, null,
                        publication.publicationId(), publication.receipt().sha256(), new String(bytes, StandardCharsets.UTF_8),
                        manifest.digest(), closure.size(), manifest.totalBytes(), request.operator(), clock.instant()));
                sources.checkRoutingUnchanged();
                GraphDeliveryClosure.requireRights(publication, registry, GraphDeliveryClosure.currentRegistry(ingestionSources), clock);
                sources.checkRoutingUnchanged();
                return result("sealed", manifest);
            });
        } catch (ArtifactStoreException refused) {
            throw new GraphDeliveryException(refused.reason() == ArtifactStoreException.Reason.BUSY ? "import_busy"
                    : refused.reason() == ArtifactStoreException.Reason.CONFLICT ? "artifact_file_conflict" : "artifact_store_unavailable");
        } catch (PublicationException refused) {
            throw new GraphDeliveryException(refused.code());
        } catch (SourceRegistry.Invalid refused) {
            throw new GraphDeliveryException("source_authority_unavailable");
        }
    }

    private byte[] receipt(String version, ArtifactFileStore.Session session) {
        ArtifactRow receipt = registry.findArtifact("artifact-receipt-" + version)
                .orElseThrow(() -> new GraphDeliveryException("package_invalid"));
        return session.read(receipt.storageUri(), receipt.sha256(), receipt.bytes());
    }

    private static void verifyFiles(ArtifactFileStore.Session session, List<ArtifactRow> rows) {
        for (ArtifactRow artifact : rows) {
            session.read(artifact.storageUri(), artifact.sha256(), artifact.bytes());
        }
    }

    private static GraphDeliveryManifest manifest(String version, String destination, GraphHandoffRequest request,
            List<ArtifactRow> rows) {
        return GraphDeliveryManifest.build(version, destination, request.handoffId(), request.expectedManifestDigest(),
                request.expectedBundleDigest(), rows);
    }

    private static void requirePins(PackageRow row, GraphHandoffRequest request) {
        if (!Objects.equals(row.handoffId(), request.handoffId()) || !Objects.equals(row.manifestDigest(), request.expectedManifestDigest())
                || !Objects.equals(row.bundleDigest(), request.expectedBundleDigest()) || row.publicationId() != null
                || row.publicationReceiptSha256() != null) throw new GraphDeliveryException("package_conflict");
    }

    private static void requireSame(PackageRow row, GraphDeliveryManifest manifest) {
        if (!row.manifest().equals(new String(manifest.bytes(), StandardCharsets.UTF_8))
                || !row.packageDigest().equals(manifest.digest()) || row.fileCount() != manifest.files().size()
                || row.totalBytes() != manifest.totalBytes() || !row.versionId().equals(manifest.versionId())
                || !row.destinationId().equals(manifest.destinationId()) || !Objects.equals(row.handoffId(), manifest.handoffId())
                || !Objects.equals(row.manifestDigest(), manifest.manifestDigest()) || !Objects.equals(row.bundleDigest(), manifest.bundleDigest())
                || !Objects.equals(row.publicationId(), manifest.publicationId())
                || !Objects.equals(row.publicationReceiptSha256(), manifest.publicationReceiptSha256())) {
            throw new GraphDeliveryException("package_conflict");
        }
    }

    private static Sealed result(String outcome, GraphDeliveryManifest manifest) {
        return new Sealed(outcome, manifest.versionId(), manifest.destinationId(), manifest.digest(), manifest.files().size(),
                manifest.totalBytes());
    }
}
