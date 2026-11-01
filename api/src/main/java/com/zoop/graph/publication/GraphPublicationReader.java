package com.zoop.graph.publication;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.TreeMap;

import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.artifact.storage.ArtifactStoreException;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import com.zoop.common.json.StrictJson.Obj;
import com.zoop.document.evidence.service.GraphReceiptGrants;
import com.zoop.document.repository.ArtifactRow;
import com.zoop.document.repository.DocumentRegistryRepository;
import com.zoop.graph.importer.GraphHandoffRepository;
import com.zoop.graph.rules.PublicationRuleEvaluator;
import com.zoop.graph.rules.RuleDefinition;
import com.zoop.graph.snapshot.GraphSnapshotCodec;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;

/** Verifies flat original provenance without depending on a public view or evidence service. */
public final class GraphPublicationReader {
    public static final String RECEIPT_SCHEMA = "zoop-graph-publication-receipt-1";
    public static final String BASIS_SCHEMA = "zoop-graph-publication-basis-1";
    public static final String POLICY = "zoop-cumulative-publication-policy-1";
    private static final JsonMapper JSON = JsonMapper.builder().build();
    private final GraphHandoffRepository graph;
    private final DocumentRegistryRepository registry;
    private final java.util.function.Function<ArtifactRow, byte[]> readArtifact;
    private final JdbcGraphPublicationRepository publications;

    public GraphPublicationReader(GraphHandoffRepository graph, DocumentRegistryRepository registry, ArtifactFileStore files,
            JdbcGraphPublicationRepository publications) {
        this(graph, registry, row -> {
            if (files == null) throw failure("basis_unavailable");
            return files.readVerified(row.storageUri(), row.sha256(), row.bytes());
        }, publications);
    }

    public GraphPublicationReader(GraphHandoffRepository graph, DocumentRegistryRepository registry,
            java.util.function.Function<ArtifactRow, byte[]> readArtifact, JdbcGraphPublicationRepository publications) {
        this.graph = graph;
        this.registry = registry;
        this.readArtifact = readArtifact;
        this.publications = publications;
    }

    public record IssueRef(String sourceVersionId, String issueId) {}
    public record RelationRef(String sourceVersionId, String relationId) {}
    public record Contribution(String sourceVersionId, String sourceId, String sourceKind, ArtifactRow receipt,
            ArtifactRow projectionArtifact, PublicGraphSnapshot projection, Obj bundle) {
        public IssueRef issueRef(String id) { return new IssueRef(sourceVersionId, id); }
    }
    public record IssueOwners(String issueId, List<IssueRef> members, Map<String, IssueRef> headlineSources) {
        public IssueOwners { members = List.copyOf(members); headlineSources = Map.copyOf(headlineSources); }
    }
    public record RelationOwners(String relationId, List<RelationRef> sources, String publicSource, String publicTarget) {
        public RelationOwners { sources = List.copyOf(sources); }
    }
    public record Publication(String versionId, String publicationId, String compositionDigest, String baseVersionId,
            String expectedActiveVersionId, ArtifactRow receipt, ArtifactRow snapshotArtifact, PublicGraphSnapshot snapshot,
            List<Contribution> contributions, Obj effectiveDecisions, Map<String, IssueOwners> issueSources,
            Map<String, RelationOwners> relationSources) {
        public Publication {
            contributions = List.copyOf(contributions);
            issueSources = Map.copyOf(issueSources);
            relationSources = Map.copyOf(relationSources);
        }
        public boolean composed() { return publicationId != null; }
        public Contribution source(String sourceVersionId) {
            return contributions.stream().filter(c -> c.sourceVersionId().equals(sourceVersionId)).findFirst()
                    .orElseThrow(() -> new PublicationException("basis_mismatch"));
        }
        public List<Contribution> articleSources(String articleId, String version) {
            return contributions.stream().filter(c -> c.projection().articles().stream()
                    .anyMatch(a -> a.articleId().equals(articleId) && a.version().equals(version))).toList();
        }
        public List<Contribution> issueContributions(String issueId) {
            IssueOwners owners = issueSources.get(issueId);
            if (owners == null) throw new PublicationException("basis_mismatch");
            return owners.members().stream().map(r -> source(r.sourceVersionId())).distinct().toList();
        }
        public List<RelationRef> selectedRelationSources(String relationId) {
            RelationOwners owners = relationSources.get(relationId);
            if (owners == null) throw new PublicationException("basis_mismatch");
            for (JsonNode node : effectiveDecisions.array("relationSelections").values()) {
                Obj selection = Obj.of(node);
                if (relationId.equals(selection.string("relationId")))
                    return List.of(PublicationMerger.relationRef(selection.object("takeFrom")));
            }
            return owners.sources();
        }
        public String publicIssue(IssueRef original) {
            return issueSources.values().stream().filter(o -> o.members().contains(original)).map(IssueOwners::issueId)
                    .findFirst().orElseThrow(() -> new PublicationException("basis_mismatch"));
        }
        public PublicGraphSnapshot.Issue originalIssue(IssueRef ref) {
            return source(ref.sourceVersionId()).projection().issues().stream().filter(i -> i.issueId().equals(ref.issueId()))
                    .findFirst().orElseThrow(() -> new PublicationException("basis_mismatch"));
        }
    }

    public Publication read(String versionId) {
        return read(versionId, null);
    }

    /** Reuses the snapshot already verified by the configured public snapshot store. */
    public Publication read(String versionId, PublicGraphSnapshot loadedSnapshot) {
        try {
            var version = graph.findVersion(versionId).orElseThrow(() -> failure("basis_unavailable"));
            if (!"snapshot".equals(version.kind())) throw failure("basis_mismatch");
            ArtifactRow snapshotRow = artifact(version.snapshotArtifactId(), Set.of("graph_snapshot"));
            PublicGraphSnapshot snapshot = loadedSnapshot == null ? GraphSnapshotCodec.read(bytes(snapshotRow), versionId) : loadedSnapshot;
            if (!versionId.equals(snapshot.versionId())) throw failure("basis_mismatch");
            ArtifactRow receiptRow = artifact("artifact-receipt-" + versionId, Set.of("verification_receipt"));
            byte[] receiptBytes = bytes(receiptRow);
            Obj receipt = StrictJson.parseObject(receiptBytes);
            if (!RECEIPT_SCHEMA.equals(receipt.string("schemaVersion"))) {
                if (publications.find(versionId).isPresent()) throw failure("basis_mismatch");
                Contribution contribution = original(versionId, null);
                var rules = graph.versionRules(versionId).stream()
                        .map(r -> new PublicationRuleEvaluator.EnabledRule(r.id(), RuleDefinition.parse(r.definition()))).toList();
                if (!snapshot.equals(PublicationRuleEvaluator.apply(contribution.projection(), rules).snapshot())) throw failure("basis_mismatch");
                var merged = PublicationMerger.merge(List.of(contribution), PublicationMerger.emptyDecisions(), Set.of());
                return new Publication(versionId, null, null, null, null, receiptRow, snapshotRow, snapshot,
                        List.of(contribution), PublicationMerger.emptyDecisions(), merged.issueSources(), merged.relationSources());
            }
            receipt.exactly(Set.of("schemaVersion", "publicationId", "compositionDigest", "basis", "snapshot",
                    "issueSources", "relationSources", "appVerification"));
            Obj basis = receipt.object("basis").exactly(Set.of("schemaVersion", "policyVersion", "baseVersionId",
                    "incomingVersionIds", "expectedActiveVersionId", "sources", "effectiveDecisions", "ruleRevision",
                    "reviewRevision", "ruleIds"));
            if (!BASIS_SCHEMA.equals(basis.string("schemaVersion")) || !POLICY.equals(basis.string("policyVersion")))
                throw failure("basis_mismatch");
            String digest = Canonical.digest(basis.node());
            String publicationId = "publication:" + digest;
            if (!digest.equals(receipt.string("compositionDigest")) || !publicationId.equals(receipt.string("publicationId"))
                    || !versionId.equals("gv-" + Canonical.sha256(publicationId)) || !publicationId.equals(snapshot.sourceBundleId()))
                throw failure("basis_mismatch");
            var metadata = publications.find(versionId).orElseThrow(() -> failure("basis_unavailable"));
            if (!metadata.equals(new JdbcGraphPublicationRepository.Metadata(versionId, publicationId, digest,
                    basis.stringOrNull("baseVersionId"), basis.stringOrNull("expectedActiveVersionId"),
                    basis.strings("incomingVersionIds")))) throw failure("basis_mismatch");
            pin(receipt.object("snapshot"), snapshotRow);
            Obj verification = receipt.object("appVerification").exactly(Set.of("policy", "nativeAnalysis", "newSemanticVerification", "publication"));
            if (!POLICY.equals(verification.string("policy")) || !"not-performed".equals(verification.string("nativeAnalysis"))
                    || !"not-performed".equals(verification.string("newSemanticVerification"))
                    || !"staged-inactive".equals(verification.string("publication"))) throw failure("basis_mismatch");
            List<Contribution> contributions = new ArrayList<>();
            Set<String> sourceIds = new HashSet<>();
            String previous = null;
            for (Obj ref : basis.objects("sources")) {
                ref.exactly(Set.of("sourceVersionId", "sourceId", "sourceKind", "receipt", "projection"));
                String sourceVersion = ref.string("sourceVersionId");
                if (previous != null && previous.compareTo(sourceVersion) >= 0) throw failure("basis_mismatch");
                previous = sourceVersion;
                Contribution source = original(sourceVersion, ref);
                if (!sourceIds.add(source.sourceId())) throw failure("source_conflict");
                contributions.add(source);
            }
            if (contributions.isEmpty()) throw failure("basis_mismatch");
            checkRows(versionId, contributions);
            List<String> incoming = basis.strings("incomingVersionIds");
            Set<String> sourceVersions = contributions.stream().map(Contribution::sourceVersionId).collect(java.util.stream.Collectors.toSet());
            if (incoming.isEmpty() || incoming.size() > 20 || !incoming.equals(incoming.stream().sorted().distinct().toList())
                    || !sourceVersions.containsAll(incoming)) throw failure("basis_mismatch");
            String baseVersion = basis.stringOrNull("baseVersionId");
            String expectedActive = basis.stringOrNull("expectedActiveVersionId");
            if (baseVersion == null) {
                if (expectedActive != null && !graph.findVersion(expectedActive).map(v -> "fixture".equals(v.kind())).orElse(false))
                    throw failure("basis_mismatch");
                if (!sourceVersions.equals(Set.copyOf(incoming))) throw failure("basis_mismatch");
            } else {
                if (!baseVersion.equals(expectedActive) || versionId.equals(baseVersion)) throw failure("basis_mismatch");
                var baseRows = graph.sources(baseVersion);
                if (baseRows.isEmpty()) throw failure("basis_unavailable");
                Set<String> required = new HashSet<>(incoming);
                Map<String, Contribution> bySource = new HashMap<>();
                contributions.forEach(c -> bySource.put(c.sourceId(), c));
                for (var row : baseRows) {
                    Contribution retained = bySource.get(row.handoffId());
                    if (retained == null) throw failure("basis_mismatch");
                    if (!retained.receipt().id().equals(row.receiptArtifactId())
                            || !retained.projectionArtifact().id().equals(row.bundleSnapshotArtifactId())) throw failure("basis_mismatch");
                    required.add(retained.sourceVersionId());
                }
                if (!sourceVersions.equals(required)) throw failure("basis_mismatch");
            }
            if (!Objects.equals(version.ruleRevision(), revision(basis, "ruleRevision"))
                    || version.reviewRevision() != revision(basis, "reviewRevision")) throw failure("basis_mismatch");
            var rules = graph.versionRules(versionId);
            if (!rules.stream().map(GraphHandoffRepository.RuleRow::id).toList().equals(basis.strings("ruleIds")))
                throw failure("basis_mismatch");
            Map<String, IssueOwners> storedOwners = new TreeMap<>();
            for (Obj item : receipt.objects("issueSources")) {
                item.exactly(Set.of("issueId", "members", "headlineSources"));
                Obj headline = item.object("headlineSources").exactly(Set.copyOf(PublicationMerger.FIELDS));
                Map<String, IssueRef> owners = new TreeMap<>();
                for (String field : PublicationMerger.FIELDS) owners.put(field, PublicationMerger.issueRef(headline.object(field)));
                String issueId = item.string("issueId");
                if (storedOwners.put(issueId, new IssueOwners(issueId, item.objects("members").stream()
                        .map(PublicationMerger::issueRef).toList(), owners)) != null) throw failure("basis_mismatch");
            }
            var merged = PublicationMerger.merge(contributions, basis.object("effectiveDecisions"), Set.of(), storedOwners);
            if (!json(merged.issueSources().values().stream().sorted(java.util.Comparator.comparing(IssueOwners::issueId)).toList())
                    .equals(receipt.raw("issueSources"))
                    || !json(merged.relationSources().values().stream().sorted(java.util.Comparator.comparing(RelationOwners::relationId)).toList())
                    .equals(receipt.raw("relationSources"))) throw failure("basis_mismatch");
            PublicGraphSnapshot expected = merged.snapshot(versionId, publicationId);
            expected = PublicationRuleEvaluator.apply(expected, rules.stream()
                    .map(r -> new PublicationRuleEvaluator.EnabledRule(r.id(), RuleDefinition.parse(r.definition()))).toList()).snapshot();
            if (!expected.equals(snapshot)) throw failure("basis_mismatch");
            return new Publication(versionId, publicationId, digest, basis.stringOrNull("baseVersionId"),
                    basis.stringOrNull("expectedActiveVersionId"), receiptRow, snapshotRow, snapshot, contributions,
                    basis.object("effectiveDecisions"), merged.issueSources(), merged.relationSources());
        } catch (StrictJson.Malformed | GraphReceiptGrants.Malformed | ArtifactStoreException
                | com.zoop.graph.snapshot.GraphSnapshotUnavailableException
                | com.zoop.graph.rules.InvalidRuleDefinitionException malformed) {
            throw failure("basis_unavailable");
        }
    }

    private Contribution original(String versionId, Obj expected) {
        var version = graph.findVersion(versionId).orElseThrow(() -> failure("basis_unavailable"));
        if (!"snapshot".equals(version.kind())) throw failure("basis_mismatch");
        var rows = graph.sources(versionId);
        if (rows.size() != 1 || rows.getFirst().ordinal() != 0) throw failure("basis_mismatch");
        var source = rows.getFirst();
        if (!versionId.equals("gv-" + Canonical.sha256(source.handoffId()))) throw failure("basis_mismatch");
        ArtifactRow receipt = artifact(source.receiptArtifactId(), Set.of("verification_receipt"));
        if (!receipt.id().equals("artifact-receipt-" + versionId)) throw failure("basis_mismatch");
        byte[] receiptBytes = bytes(receipt);
        Obj receiptDocument = StrictJson.parseObject(receiptBytes);
        Obj bundle = GraphReceiptGrants.bundle(receiptBytes, versionId);
        ArtifactRow projection = artifact(source.bundleSnapshotArtifactId(), Set.of("graph_snapshot", "graph_bundle_snapshot"));
        PublicGraphSnapshot snapshot = GraphSnapshotCodec.read(bytes(projection), versionId);
        if (!source.handoffId().equals(snapshot.sourceBundleId())) throw failure("basis_mismatch");
        boolean legacy = com.zoop.graph.importer.LegacyRealPackage.isReceiptSchema(receiptDocument.string("schemaVersion"));
        String kind = legacy ? "legacy-real" : "native";
        if (!source.handoffId().equals(receiptDocument.string(legacy ? "migrationId" : "handoffId"))) throw failure("basis_mismatch");
        if (expected != null) {
            if (!expected.string("sourceId").equals(source.handoffId()) || !expected.string("sourceKind").equals(kind))
                throw failure("basis_mismatch");
            pin(expected.object("receipt"), receipt);
            pin(expected.object("projection"), projection);
        }
        return new Contribution(versionId, source.handoffId(), kind, receipt, projection, snapshot, bundle);
    }

    private void checkRows(String versionId, List<Contribution> contributions) {
        var rows = graph.sources(versionId);
        if (rows.size() != contributions.size()) throw failure("basis_mismatch");
        for (int index = 0; index < rows.size(); index++) {
            var row = rows.get(index);
            var source = contributions.get(index);
            if (row.ordinal() != index || !row.handoffId().equals(source.sourceId())
                    || !row.receiptArtifactId().equals(source.receipt().id())
                    || !Objects.equals(row.bundleSnapshotArtifactId(), source.projectionArtifact().id())) throw failure("basis_mismatch");
        }
    }

    public List<ArtifactRow> closure(Publication publication) {
        Map<String, ArtifactRow> rows = new TreeMap<>();
        add(rows, publication.snapshotArtifact());
        add(rows, publication.receipt());
        for (Contribution source : publication.contributions()) {
            add(rows, source.receipt());
            add(rows, source.projectionArtifact());
            for (var article : source.projection().articles()) {
                var version = registry.findVersion(article.articleId(), article.version()).orElseThrow(() -> failure("basis_unavailable"));
                ArtifactRow text = artifact(version.textArtifactId(), Set.of("extracted_text"));
                if (add(rows, text)) bytes(text);
            }
        }
        if (rows.size() > 1003 || rows.values().stream().mapToLong(ArtifactRow::bytes).sum() > 256L * 1024 * 1024)
            throw failure("publication_too_large");
        if (rows.values().stream().map(ArtifactRow::storageUri).distinct().count() != rows.size()) throw failure("basis_mismatch");
        return List.copyOf(rows.values());
    }

    private static boolean add(Map<String, ArtifactRow> rows, ArtifactRow row) {
        ArtifactRow previous = rows.putIfAbsent(row.id(), row);
        if (previous != null && !previous.equals(row)) throw failure("basis_mismatch");
        if (rows.size() > 1003) throw failure("publication_too_large");
        return previous == null;
    }

    public ArtifactRow artifact(String id, Set<String> kinds) {
        if (id == null) throw failure("basis_unavailable");
        ArtifactRow row = registry.findArtifact(id).orElseThrow(() -> failure("basis_unavailable"));
        if (!kinds.contains(row.kind()) || row.bytes() > ArtifactFileStore.MAX_READ_BYTES || row.bytes() < 0
                || (!"extracted_text".equals(row.kind()) && !"application/json".equals(row.mediaType()))) throw failure("basis_mismatch");
        return row;
    }

    public byte[] bytes(ArtifactRow row) {
        byte[] bytes = readArtifact.apply(row);
        if (bytes.length != row.bytes() || bytes.length > ArtifactFileStore.MAX_READ_BYTES
                || !Canonical.sha256(bytes).equals(row.sha256())) throw failure("basis_mismatch");
        return bytes;
    }

    public static ObjectNode pin(ArtifactRow row) {
        ObjectNode out = StrictJson.newObject();
        out.put("artifactId", row.id()); out.put("sha256", row.sha256()); out.put("bytes", row.bytes());
        return out;
    }

    public static void pin(Obj pin, ArtifactRow row) {
        pin.exactly(Set.of("artifactId", "sha256", "bytes"));
        if (!pin.string("artifactId").equals(row.id()) || !pin.string("sha256").equals(row.sha256())
                || revision(pin, "bytes") != row.bytes()) throw failure("basis_mismatch");
    }

    public static long revision(Obj object, String field) {
        JsonNode value = object.raw(field);
        if (!value.isIntegralNumber() || !value.canConvertToLong() || value.longValue() < 0) throw new StrictJson.Malformed();
        return value.longValue();
    }

    public static JsonNode json(Object value) { return JSON.valueToTree(value); }
    public static byte[] snapshotBytes(PublicGraphSnapshot snapshot) { return Canonical.appBytes(json(snapshot)); }
    private static PublicationException failure(String code) { return new PublicationException(code); }
}
