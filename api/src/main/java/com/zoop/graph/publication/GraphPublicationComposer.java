package com.zoop.graph.publication;

import java.time.Clock;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.TreeMap;
import java.util.TreeSet;
import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.artifact.storage.ArtifactStoreException;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import com.zoop.common.json.StrictJson.Obj;
import com.zoop.document.evidence.service.DocumentReadSources;
import com.zoop.document.repository.ArtifactRow;
import com.zoop.document.repository.DocumentRegistryRepository;
import com.zoop.graph.importer.GraphHandoffRepository;
import com.zoop.graph.publication.GraphPublicationReader.Contribution;
import com.zoop.graph.publication.GraphPublicationReader.Publication;
import com.zoop.graph.rules.PublicationRuleEvaluator;
import com.zoop.graph.rules.RuleDefinition;
import com.zoop.graph.snapshot.GraphSnapshotCodec;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import com.zoop.graph.version.GraphVersionRepository;
import org.springframework.dao.DataAccessException;
import org.springframework.transaction.TransactionException;
import org.springframework.transaction.support.TransactionOperations;
import tools.jackson.databind.node.ObjectNode;

public final class GraphPublicationComposer {
    private final ArtifactFileStore files;
    private final GraphHandoffRepository graph;
    private final DocumentRegistryRepository registry;
    private final GraphVersionRepository versions;
    private final JdbcGraphPublicationRepository publications;
    private final GraphPublicationReader reader;
    private final GraphPublicationAuthority authority;
    private final DocumentReadSources sources;
    private final TransactionOperations transaction;
    private final Clock clock;

    public GraphPublicationComposer(ArtifactFileStore files, GraphHandoffRepository graph, DocumentRegistryRepository registry,
            GraphVersionRepository versions, JdbcGraphPublicationRepository publications, GraphPublicationReader reader,
            GraphPublicationAuthority authority, DocumentReadSources sources, TransactionOperations transaction, Clock clock) {
        this.files = files; this.graph = graph; this.registry = registry; this.versions = versions; this.publications = publications;
        this.reader = reader; this.authority = authority; this.sources = sources; this.transaction = transaction; this.clock = clock;
    }

    public ObjectNode run(PublicationComposeRequest request, byte[] decisionsBytes) {
        if (decisionsBytes.length > 4_000_000 || !Canonical.sha256(decisionsBytes).equals(request.decisionsSha256())) return failed("request_invalid");
        try (var session = files.open()) {
            List<ArtifactFileStore.StoredFile> created = new ArrayList<>();
            try {
                Obj decisions = StrictJson.parseObject(decisionsBytes);
                var routing = sources.registry(null);
                return transaction.execute(status -> {
                    try {
                        ObjectNode answer = compose(session, request, decisions, created);
                        routing.checkRoutingUnchanged();
                        return answer;
                    } catch (DataAccessException error) { throw new PublicationException("database_unavailable"); }
                    catch (com.zoop.document.importer.SourceRegistry.Invalid error) { throw new PublicationException("source_authority_unavailable"); }
                    catch (ArtifactStoreException error) { throw new PublicationException("basis_unavailable"); }
                    catch (com.zoop.graph.snapshot.GraphSnapshotUnavailableException
                            | com.zoop.graph.rules.InvalidRuleDefinitionException error) { throw new PublicationException("basis_mismatch"); }
                });
            } catch (PublicationException rolledBack) {
                created.forEach(session::discard);
                return failed(rolledBack.code());
            } catch (StrictJson.Malformed malformed) {
                created.forEach(session::discard);
                return failed("request_invalid");
            } catch (DataAccessException | TransactionException unknownCommit) {
                return failed("outcome_unknown");
            }
        } catch (ArtifactStoreException failure) {
            return failed(failure.reason() == ArtifactStoreException.Reason.BUSY ? "import_busy" : "basis_unavailable");
        } catch (com.zoop.common.exception.CustomException failure) {
            return failed("source_authority_unavailable");
        }
    }

    private ObjectNode compose(ArtifactFileStore.Session session, PublicationComposeRequest request, Obj decisions,
            List<ArtifactFileStore.StoredFile> created) {
        graph.lockCatalog();
        publications.lockPublication();
        var active = versions.active().orElse(null);
        String activeId = active == null ? null : active.id();
        if (!Objects.equals(activeId, request.expectedActiveVersionId())) throw failure("active_conflict");
        if (request.baseVersionId() == null) {
            if (active != null && !"fixture".equals(active.kind())) throw failure("active_conflict");
        } else if (!request.baseVersionId().equals(activeId) || active == null || "fixture".equals(active.kind())) throw failure("active_conflict");
        var state = graph.publicationState();
        if (state.ruleRevision() != request.expectedRuleRevision() || state.reviewRevision() != request.expectedReviewRevision()) throw failure("revision_conflict");
        Publication base = request.baseVersionId() == null ? null : reader.read(request.baseVersionId());
        if (base != null && !base.receipt().sha256().equals(request.expectedBaseReceiptSha256())) throw failure("basis_mismatch");
        Map<String, Contribution> byId = new TreeMap<>();
        if (base != null) base.contributions().forEach(c -> add(byId, c));
        for (String incoming : request.incomingVersionIds()) {
            Publication input = reader.read(incoming);
            if (input.composed() || input.contributions().size() != 1) throw failure("basis_mismatch");
            if (!input.receipt().sha256().equals(request.incomingReceiptPins().get(incoming))) throw failure("basis_mismatch");
            add(byId, input.contributions().getFirst());
        }
        List<Contribution> contributions = byId.values().stream().sorted(java.util.Comparator.comparing(Contribution::sourceVersionId)).toList();
        Obj effective = PublicationMerger.combine(base == null ? PublicationMerger.emptyDecisions() : base.effectiveDecisions(), decisions);
        if (base != null) {
            Map<String, PublicGraphSnapshot.Issue> current = new java.util.HashMap<>();
            var baseMerged = PublicationMerger.merge(base.contributions(), base.effectiveDecisions(), Set.of(), base.issueSources());
            baseMerged.issues().forEach(i -> current.put(i.issueId(), i));
            for (Obj choice : decisions.objects("fieldSelections")) {
                var previous = current.get(choice.string("issueId"));
                if (previous != null && !choice.string("expectedValueDigest").equals(Canonical.digest(PublicationMerger.field(previous, choice.string("field")))))
                    throw failure("identity_conflict");
            }
            for (Obj choice : decisions.objects("relationSelections")) {
                var previous = baseMerged.relations().stream().filter(r -> r.relationId().equals(choice.string("relationId"))).findFirst();
                if (previous.isPresent() && !choice.string("expectedValueDigest").equals(Canonical.digest(GraphPublicationReader.json(previous.get()))))
                    throw failure("identity_conflict");
            }
        }
        Set<String> publicIds = new java.util.HashSet<>(base == null ? Set.of() : base.issueSources().keySet());
        Set<String> mappingSources = decisions.objects("issueMappings").stream()
                .map(d -> d.object("from").string("sourceVersionId")).collect(java.util.stream.Collectors.toSet());
        for (String previousId : publications.publishedVersionsForSources(mappingSources)) {
            var previous = graph.findVersion(previousId).orElseThrow(() -> failure("basis_unavailable"));
            var artifact = reader.artifact(previous.snapshotArtifactId(), Set.of("graph_snapshot"));
            GraphSnapshotCodec.read(reader.bytes(artifact), previousId).issues().forEach(i -> publicIds.add(i.issueId()));
        }
        var merged = PublicationMerger.merge(contributions, effective, publicIds, base == null ? Map.of() : base.issueSources());
        var catalog = graph.companies(merged.companies().stream().map(PublicGraphSnapshot.Company::companyId).toList());
        for (var company : merged.companies()) {
            var registered = catalog.get(company.companyId());
            if (registered == null || !registered.name().equals(company.label())) throw failure("identity_conflict");
        }
        TreeSet<String> articleIds = new TreeSet<>(); contributions.forEach(c -> c.projection().articles().forEach(a -> articleIds.add(a.articleId())));
        for (String id : articleIds) registry.lockArticle(id).orElseThrow(() -> failure("basis_unavailable"));
        authority.requireFullRights(contributions, null);
        verifyEvidence(contributions);
        ObjectNode basis = StrictJson.newObject(); basis.put("schemaVersion", GraphPublicationReader.BASIS_SCHEMA);
        basis.put("policyVersion", GraphPublicationReader.POLICY); basis.put("baseVersionId", request.baseVersionId());
        basis.set("incomingVersionIds", GraphPublicationReader.json(request.incomingVersionIds()));
        basis.put("expectedActiveVersionId", request.expectedActiveVersionId());
        var sourceNodes = basis.putArray("sources");
        for (Contribution source : contributions) {
            var node = sourceNodes.addObject(); node.put("sourceVersionId", source.sourceVersionId()); node.put("sourceId", source.sourceId()); node.put("sourceKind", source.sourceKind());
            node.set("receipt", GraphPublicationReader.pin(source.receipt())); node.set("projection", GraphPublicationReader.pin(source.projectionArtifact()));
        }
        basis.set("effectiveDecisions", effective.node()); basis.put("ruleRevision", state.ruleRevision()); basis.put("reviewRevision", state.reviewRevision());
        basis.set("ruleIds", GraphPublicationReader.json(state.enabledRules().stream().map(GraphHandoffRepository.RuleRow::id).toList()));
        String digest = Canonical.digest(basis); String publicationId = "publication:" + digest; String versionId = "gv-" + Canonical.sha256(publicationId);
        PublicGraphSnapshot snapshot = PublicationRuleEvaluator.apply(merged.snapshot(versionId, publicationId), state.enabledRules().stream()
                .map(r -> new PublicationRuleEvaluator.EnabledRule(r.id(), RuleDefinition.parse(r.definition()))).toList()).snapshot();
        byte[] snapshotBytes = GraphPublicationReader.snapshotBytes(snapshot);
        GraphSnapshotCodec.read(snapshotBytes, versionId);
        Instant now = clock.instant();
        var snapshotRow = row("artifact-" + versionId, "graph_snapshot", versionId, snapshotBytes, now);
        ObjectNode receipt = StrictJson.newObject(); receipt.put("schemaVersion", GraphPublicationReader.RECEIPT_SCHEMA);
        receipt.put("publicationId", publicationId); receipt.put("compositionDigest", digest); receipt.set("basis", basis);
        receipt.set("snapshot", GraphPublicationReader.pin(snapshotRow));
        receipt.set("issueSources", GraphPublicationReader.json(merged.issueSources().values().stream().sorted(java.util.Comparator.comparing(GraphPublicationReader.IssueOwners::issueId)).toList()));
        receipt.set("relationSources", GraphPublicationReader.json(merged.relationSources().values().stream().sorted(java.util.Comparator.comparing(GraphPublicationReader.RelationOwners::relationId)).toList()));
        var verification = receipt.putObject("appVerification"); verification.put("policy", GraphPublicationReader.POLICY);
        verification.put("nativeAnalysis", "not-performed"); verification.put("newSemanticVerification", "not-performed"); verification.put("publication", "staged-inactive");
        byte[] receiptBytes = Canonical.appBytes(receipt);
        if (snapshotBytes.length > ArtifactFileStore.MAX_READ_BYTES || receiptBytes.length > ArtifactFileStore.MAX_READ_BYTES) throw failure("publication_too_large");
        var receiptRow = row("artifact-receipt-" + versionId, "verification_receipt", versionId, receiptBytes, now);
        var candidate = new Publication(versionId, publicationId, digest, request.baseVersionId(), request.expectedActiveVersionId(), receiptRow,
                snapshotRow, snapshot, contributions, effective, merged.issueSources(), merged.relationSources());
        reader.closure(candidate);
        boolean exists = graph.findVersion(versionId).isPresent();
        if (exists) {
            Publication previous = reader.read(versionId);
            if (!previous.receipt().sha256().equals(receiptRow.sha256()) || !previous.snapshotArtifact().sha256().equals(snapshotRow.sha256())
                    || !Arrays.equals(reader.bytes(previous.receipt()), receiptBytes) || !Arrays.equals(reader.bytes(previous.snapshotArtifact()), snapshotBytes)) throw failure("basis_mismatch");
        } else {
            store(session, snapshotRow, snapshotBytes, created); store(session, receiptRow, receiptBytes, created);
            graph.insertStagedVersion(new GraphHandoffRepository.NewStagedVersion(versionId, "operator:" + request.operator(), "operator cumulative publication: staged, not activated",
                    publicationId, GraphPublicationReader.POLICY, snapshotRow.id(), snapshot.issues().size(), snapshot.relations().size(), snapshot.articles().size(), now,
                    state.ruleRevision(), state.reviewRevision(), state.enabledRules().stream().map(GraphHandoffRepository.RuleRow::id).toList()));
            for (int index = 0; index < contributions.size(); index++) {
                var source = contributions.get(index); graph.insertSource(new GraphHandoffRepository.NewSource(versionId, index, source.sourceId(), source.receipt().id(), source.projectionArtifact().id()));
            }
            publications.insert(new JdbcGraphPublicationRepository.Metadata(versionId, publicationId, digest, request.baseVersionId(), request.expectedActiveVersionId(), request.incomingVersionIds()));
        }
        authority.requireFullRights(contributions, null);
        ObjectNode result = StrictJson.newObject(); result.put("schemaVersion", "zoop-graph-publication-compose-result-1"); result.put("status", "succeeded");
        result.put("outcome", exists ? "unchanged" : "staged"); result.put("publicationId", publicationId); result.put("graphVersionId", versionId);
        result.put("baseVersionId", request.baseVersionId()); result.set("incomingVersionIds", GraphPublicationReader.json(request.incomingVersionIds()));
        result.put("expectedActiveVersionId", request.expectedActiveVersionId()); result.put("compositionDigest", digest); result.put("receiptSha256", receiptRow.sha256());
        var counts = result.putObject("counts"); counts.put("sources", contributions.size()); counts.put("companies", snapshot.companies().size());
        counts.put("issues", snapshot.issues().size()); counts.put("relations", snapshot.relations().size()); counts.put("articles", snapshot.articles().size()); counts.put("evidence", snapshot.evidence().size());
        result.put("activation", "not-activated"); return result;
    }

    private void verifyEvidence(List<Contribution> contributions) {
        for (Contribution source : contributions) {
            Map<String, Obj> proof = new java.util.HashMap<>(); source.bundle().objects("evidence").forEach(e -> proof.put(e.string("id"), e));
            for (var span : source.projection().evidence()) {
                var stored = graph.findEvidence(span.evidenceId()).orElseThrow(() -> failure("basis_unavailable")); var row = stored.row();
                Obj original = proof.get(span.evidenceId());
                if (original == null || !row.articleId().equals(span.articleId()) || !row.articleVersion().equals(span.articleVersion())
                        || row.startOffset() != span.start() || row.endOffset() != span.end() || !Boolean.TRUE.equals(stored.quoteVerified())
                        || !"body".equals(stored.inputKind()) || !"unicode_code_point".equals(stored.offsetUnit())
                        || !"verification_receipt".equals(stored.verificationKind()) || stored.summaryAnalysisId() != null
                        || !Canonical.sha256(row.quote()).equals(original.string("quoteSha256"))) throw failure("identity_conflict");
                var version = registry.findVersion(row.articleId(), row.articleVersion()).orElseThrow(() -> failure("basis_unavailable"));
                if (!version.textArtifactId().equals(row.textArtifactId())) throw failure("basis_mismatch");
                if ("native".equals(source.sourceKind()) && !row.rawLocatorIds().equals(original.strings("rawLocatorIds"))) throw failure("identity_conflict");
            }
        }
    }

    private static void add(Map<String, Contribution> sources, Contribution source) {
        Contribution old = sources.putIfAbsent(source.sourceId(), source);
        if (old != null && (!old.sourceVersionId().equals(source.sourceVersionId()) || !old.receipt().equals(source.receipt())
                || !old.projectionArtifact().equals(source.projectionArtifact()))) throw failure("source_conflict");
    }
    private static ArtifactRow row(String id, String kind, String version, byte[] bytes, Instant now) {
        return new ArtifactRow(id, kind, "artifact-root:" + kind + "/" + version + ".json", Canonical.sha256(bytes), bytes.length, "application/json", now);
    }
    private void store(ArtifactFileStore.Session session, ArtifactRow row, byte[] bytes, List<ArtifactFileStore.StoredFile> created) {
        var stored = session.put(row.kind(), row.id().startsWith("artifact-receipt-") ? row.id().substring("artifact-receipt-".length()) + ".json"
                : row.id().substring("artifact-".length()) + ".json", bytes);
        created.add(stored);
        if (!stored.uri().equals(row.storageUri()) || !stored.sha256().equals(row.sha256())) throw failure("basis_mismatch");
        if (!registry.insertArtifactIfAbsent(row)) {
            var previous = registry.findArtifact(row.id()).orElseThrow(() -> failure("basis_mismatch"));
            if (!previous.kind().equals(row.kind()) || !previous.storageUri().equals(row.storageUri()) || !previous.sha256().equals(row.sha256())
                    || previous.bytes() != row.bytes() || !previous.mediaType().equals(row.mediaType())) throw failure("basis_mismatch");
        }
    }
    public static ObjectNode failed(String code) {
        ObjectNode result = StrictJson.newObject(); result.put("schemaVersion", "zoop-graph-publication-compose-result-1"); result.put("status", "failed"); result.put("code", code); return result;
    }
    private static PublicationException failure(String code) { return new PublicationException(code); }
}
