package com.zoop.graph.importer;

import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import com.zoop.common.json.StrictJson.Obj;
import com.zoop.document.analysis.repository.EvidenceRow;
import com.zoop.document.importer.SourceRegistry;
import com.zoop.document.repository.ArtifactRow;
import com.zoop.document.repository.DocumentRegistryRepository;
import com.zoop.document.service.ArticleKind;
import com.zoop.document.service.DocumentRegistrationService;
import com.zoop.document.service.PointerPolicy;
import com.zoop.document.service.RegistrationCommand;
import com.zoop.graph.importer.GraphHandoffRepository.NewSource;
import com.zoop.graph.importer.GraphHandoffRepository.NewStagedVersion;
import com.zoop.graph.importer.GraphHandoffRepository.RuleRow;
import com.zoop.graph.importer.LegacyRealPackage.Invalid;
import com.zoop.graph.importer.LegacyRealPackage.Projection;
import com.zoop.graph.importer.LegacyRealPackage.Request;
import com.zoop.graph.rules.PublicationRuleEvaluator;
import com.zoop.graph.rules.RuleDefinition;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.time.Clock;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import org.springframework.dao.DataAccessException;
import org.springframework.transaction.TransactionException;
import org.springframework.transaction.support.TransactionOperations;
import tools.jackson.databind.node.ObjectNode;

/** OS-authorized serving-side import; the source registry is read at admission and immediately before commit. */
public final class LegacyRealImporter {
    private final Path packageRoot;
    private final Path sources;
    private final ArtifactFileStore store;
    private final DocumentRegistryRepository registry;
    private final DocumentRegistrationService documents;
    private final GraphHandoffRepository graph;
    private final TransactionOperations transaction;
    private final Clock clock;

    public LegacyRealImporter(Path packageRoot, Path sources, ArtifactFileStore store, DocumentRegistryRepository registry,
            DocumentRegistrationService documents, GraphHandoffRepository graph, TransactionOperations transaction, Clock clock) {
        this.packageRoot = packageRoot; this.sources = sources; this.store = store; this.registry = registry;
        this.documents = documents; this.graph = graph; this.transaction = transaction; this.clock = clock;
    }

    public ObjectNode run(Request request) {
        Projection projection = LegacyRealPackage.read(packageRoot, request);
        ObjectNode result = StrictJson.newObject();
        result.put("schemaVersion", "zoop-legacy-real-import-result-1"); result.put("sourceKind", "legacy-real");
        result.put("migrationId", request.migrationId()); result.put("graphVersionId", projection.versionId());
        result.put("validatedIssues", projection.graph().issues().size()); result.put("validatedEvidence", projection.evidence().size());
        result.put("contentDigest", Canonical.digest(projection.bundle().node()));
        try (var session = store.open()) {
            rights(projection);
            List<ArtifactFileStore.StoredFile> files = new ArrayList<>();
            String outcome;
            try {
                outcome = transaction.execute(status -> {
                    try { return stage(session, projection, files); }
                    catch (DataAccessException error) { throw new Invalid("database_statement_failed"); }
                });
            } catch (DataAccessException | TransactionException unknown) {
                throw new Invalid("database_outcome_unknown");
            } catch (RuntimeException rolledBack) {
                files.forEach(session::discard);
                throw rolledBack;
            }
            result.put("status", "succeeded"); result.put("outcome", outcome); result.put("activation", "not-activated");
            result.put("manifestDigest", request.expectedManifestDigest()); result.put("bundleDigest", request.expectedBundleDigest());
            var artifactIds = new java.util.LinkedHashSet<String>();
            artifactIds.add("artifact-" + projection.versionId()); artifactIds.add("artifact-receipt-" + projection.versionId());
            graph.sources(projection.versionId()).forEach(source -> artifactIds.add(source.bundleSnapshotArtifactId()));
            projection.articles().forEach(article -> artifactIds.add("artifact-legacy-text-" + Canonical.sha256(
                    article.projected().string("articleId") + "\n" + article.projected().string("articleVersion"))));
            var output = result.putArray("artifacts");
            for (String id : artifactIds) {
                ArtifactRow row = registry.findArtifact(id).orElseThrow(() -> new Invalid("artifact_missing"));
                var entry = output.addObject(); entry.put("artifactId", id); entry.put("kind", row.kind());
                entry.put("storageUri", row.storageUri()); entry.put("sha256", row.sha256()); entry.put("bytes", row.bytes());
            }
        } catch (Invalid denied) {
            result.put("status", "failed"); result.put("code", denied.getMessage());
        }
        return result;
    }

    private String stage(ArtifactFileStore.Session session, Projection p, List<ArtifactFileStore.StoredFile> files) {
        graph.lockCatalog();
        var state = graph.publicationState();
        var original = p.graph();
        var catalogue = graph.companies(original.companies().stream().map(c -> c.companyId()).toList());
        for (Obj binding : p.manifest().objects("companyBindings")) {
            var company = catalogue.get(binding.string("companyId"));
            LegacyRealPackage.need(company != null && company.name().equals(binding.string("canonicalName"))
                    && (company.name().equals(binding.string("originalName"))
                        || company.aliases().contains(binding.string("originalName"))), "company_mismatch");
        }
        LegacyRealPackage.need(graph.companies(original.issues().stream().map(i -> i.issueId()).toList()).isEmpty(), "company_issue_collision");
        String version = p.versionId(), snapshotId = "artifact-" + version, receiptId = "artifact-receipt-" + version;
        var existing = graph.findVersion(version);
        if (existing.isPresent()) {
            LegacyRealPackage.need("snapshot".equals(existing.get().kind()) && snapshotId.equals(existing.get().snapshotArtifactId()), "version_conflict");
            checkArtifact(session, receiptId, "verification_receipt", p.receipt());
        }
        List<RuleRow> rules = existing.isPresent() ? graph.versionRules(version) : state.enabledRules();
        var enabled = rules.stream().map(r -> new PublicationRuleEvaluator.EnabledRule(r.id(), RuleDefinition.parse(r.definition()))).toList();
        var filtered = PublicationRuleEvaluator.apply(original, enabled).snapshot();
        byte[] visible = filtered.equals(original) ? p.snapshot() : HandoffSnapshotWriter.keepOnly(p.snapshot(), filtered);
        for (var article : p.articles()) {
            Obj a = article.projected(), grant = a.object("grantBinding");
            String textId = "artifact-legacy-text-" + Canonical.sha256(a.string("articleId") + "\n" + a.string("articleVersion"));
            byte[] text = article.body().getBytes(StandardCharsets.UTF_8);
            if (existing.isPresent()) {
                checkArtifact(session, textId, "extracted_text", text);
                var row = registry.lockArticle(a.string("articleId")).orElseThrow(() -> new Invalid("article_missing"));
                var stored = registry.findVersion(a.string("articleId"), a.string("articleVersion")).orElseThrow(() -> new Invalid("article_missing"));
                LegacyRealPackage.need("available".equals(row.accessStatus()) && row.provider().equals(grant.string("sourceId"))
                        && textId.equals(stored.textArtifactId()) && a.string("url").equals(stored.url()), "article_conflict");
            } else {
                var textFile = put(session, files, "extracted_text", textId + ".txt", text);
                String precision = a.string("publicationPrecision"), published = a.stringOrNull("publishedAt");
                documents.register(new RegistrationCommand(a.string("articleId"), a.string("articleVersion"), grant.string("sourceId"),
                        ArticleKind.fromWire(grant.string("kind")).orElseThrow(), textId, textFile.uri(), textFile.sha256(), textFile.bytes(),
                        a.string("title"), a.string("url"), a.stringOrNull("publisher"),
                        "datetime".equals(precision) ? HandoffTime.instant(published) : null,
                        "day".equals(precision) ? LocalDate.parse(published) : null, precision,
                        HandoffTime.instant(a.string("collectedAt")), PointerPolicy.keep()));
                var stored = registry.findVersion(a.string("articleId"), a.string("articleVersion")).orElseThrow();
                LegacyRealPackage.need(a.string("url").equals(stored.url()), "article_url_conflict");
            }
        }
        String bundleId = Arrays.equals(visible, p.snapshot()) ? snapshotId : "artifact-bundle-" + version;
        if (existing.isPresent()) {
            checkArtifact(session, snapshotId, "graph_snapshot", visible);
            checkArtifact(session, bundleId, bundleId.equals(snapshotId) ? "graph_snapshot" : "graph_bundle_snapshot", p.snapshot());
            var sources = graph.sources(version);
            LegacyRealPackage.need(sources.size() == 1 && sources.getFirst().ordinal() == 0
                    && sources.getFirst().handoffId().equals(p.request().migrationId()) && sources.getFirst().receiptArtifactId().equals(receiptId)
                    && bundleId.equals(sources.getFirst().bundleSnapshotArtifactId()), "version_source_conflict");
        } else {
            register(snapshotId, "graph_snapshot", put(session, files, "graph_snapshot", GraphHandoffImporter.snapshotFileName(version, rules.stream().map(RuleRow::id).toList()), visible));
            register(receiptId, "verification_receipt", put(session, files, "verification_receipt", version + ".json", p.receipt()));
            if (!bundleId.equals(snapshotId)) register(bundleId, "graph_bundle_snapshot", put(session, files, "graph_bundle", version + ".json", p.snapshot()));
        }
        for (Obj e : p.evidence()) {
            String textId = "artifact-legacy-text-" + Canonical.sha256(e.string("articleId") + "\n" + e.string("articleVersion"));
            var wanted = new EvidenceRow(e.string("id"), e.string("articleId"), e.string("articleVersion"), textId,
                    e.string("quote"), e.count("start"), e.count("end"), List.of(e.string("locatorId")), receiptId, clock.instant(), clock.instant());
            var found = graph.findEvidence(wanted.id());
            if (found.isPresent()) LegacyRealPackage.need(GraphHandoffImporter.sameEvidence(found.get(), wanted), "evidence_collision");
            else { LegacyRealPackage.need(existing.isEmpty(), "evidence_missing"); graph.insertEvidence(wanted); }
        }
        if (existing.isEmpty()) {
            graph.insertStagedVersion(new NewStagedVersion(version, "operator:" + p.request().operator(), "legacy-real retained-result import",
                    p.request().migrationId(), p.policyVersion(), snapshotId, filtered.issues().size(), filtered.relations().size(),
                    filtered.articles().size(), clock.instant(), state.ruleRevision(), state.reviewRevision(), rules.stream().map(RuleRow::id).toList()));
            graph.insertSource(new NewSource(version, 0, p.request().migrationId(), receiptId, bundleId));
        }
        LegacyRealPackage.recheck(packageRoot, p);
        rights(p);
        return existing.isPresent() ? "unchanged" : "staged";
    }

    private void rights(Projection p) {
        SourceRegistry current = SourceRegistry.read(sources);
        for (var article : p.articles()) {
            Obj a = article.projected(); LegacyRealPackage.need(!a.isNull("grantBinding"), "current_grant_binding_missing");
            Obj grant = a.object("grantBinding");
            String denial = current.denialForUrl(grant.string("sourceId"), grant.string("grantId"), grant.string("revision"), a.string("url"), clock.instant());
            LegacyRealPackage.need(denial == null, "current_grant_" + denial);
        }
    }
    private ArtifactFileStore.StoredFile put(ArtifactFileStore.Session session, List<ArtifactFileStore.StoredFile> files,
            String directory, String name, byte[] bytes) {
        LegacyRealPackage.need(bytes.length <= ArtifactFileStore.MAX_READ_BYTES, "artifact_too_large");
        var file = session.put(directory, name, bytes); files.add(file); return file;
    }
    private void register(String id, String kind, ArtifactFileStore.StoredFile file) {
        var wanted = new ArtifactRow(id, kind, file.uri(), file.sha256(), file.bytes(), "application/json", clock.instant());
        registry.insertArtifactIfAbsent(wanted);
        var found = registry.findArtifact(id).orElseThrow(() -> new Invalid("artifact_missing"));
        LegacyRealPackage.need(found.kind().equals(kind) && found.storageUri().equals(file.uri()) && found.sha256().equals(file.sha256())
                && found.bytes() == file.bytes() && found.mediaType().equals(wanted.mediaType()), "artifact_conflict");
    }
    private void checkArtifact(ArtifactFileStore.Session session, String id, String kind, byte[] expected) {
        var row = registry.findArtifact(id).orElseThrow(() -> new Invalid("artifact_missing"));
        LegacyRealPackage.need(kind.equals(row.kind()) && row.sha256().equals(Canonical.sha256(expected)) && row.bytes() == expected.length
                && Arrays.equals(session.read(row.storageUri(), row.sha256(), row.bytes()), expected), "artifact_conflict");
    }
}
