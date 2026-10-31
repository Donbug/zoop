package com.zoop.graph.importer;

import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import com.zoop.common.json.StrictJson.Obj;
import com.zoop.document.service.DocumentRegistrationService;
import com.zoop.document.service.InMemoryDocumentRegistry;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.transaction.support.TransactionCallback;
import org.springframework.transaction.support.TransactionOperations;
import tools.jackson.databind.node.ObjectNode;
import static org.junit.jupiter.api.Assertions.*;

class LegacyRealImporterTest {
    @TempDir Path temporary;
    private Path root, artifacts, sources;
    private ObjectNode selection, geography, manifest, metadataPolicy;
    private InMemoryDocumentRegistry registry;
    private InMemoryGraphHandoffRepository graph;
    private LegacyRealImporter importer;
    private final Clock clock = Clock.fixed(Instant.parse("2026-10-30T00:00:00Z"), ZoneOffset.UTC);
    private String version;
    private Runnable afterAdmission;

    @BeforeEach void setup() throws Exception {
        root = Files.createDirectory(temporary.toRealPath().resolve("package"));
        artifacts = Files.createDirectory(temporary.toRealPath().resolve("artifacts"));
        sources = temporary.toRealPath().resolve("sources.json");
        String text;
        try (var resource = getClass().getResourceAsStream("/legacy-real/selection.json")) {
            text = new String(resource.readAllBytes(), java.nio.charset.StandardCharsets.UTF_8);
        }
        Obj raw = StrictJson.parseObject(text);
        ObjectNode article = (ObjectNode) raw.objects("articles").getFirst().object("record").node().deepCopy();
        article.remove("collected_at"); version = Canonical.digest(article);
        selection = (ObjectNode) StrictJson.parseObject(text.replace("VERSION", version)).node();
        selection.put("selection_basis", "selected-bound-article-and-geography");
        ((ObjectNode) selection.get("candidate_audit").get(0)).set("original_mention", selection.get("issues").get(0).get("mentions").get(0).deepCopy());
        geography = StrictJson.newObject(); geography.put("schema", "zoop-legacy-geography-review/1");
        geography.putNull("policy_version"); geography.putNull("review_date");
        ObjectNode geo = geography.putArray("records").addObject(); geo.put("issue_id", "issue-synthetic-lab");
        geo.put("decision", "source_supported"); geo.put("classification", "domestic"); geo.put("review_policy_version", "legacy-source-geography-review/1");
        geo.put("reviewer", "local-source-review"); geo.put("reason", "selected_source_evidence");
        geo.putArray("country_codes").add("KR"); geo.putArray("regions"); geo.putArray("source_evidence_ids").add("geo-synthetic");
        ObjectNode span = (ObjectNode) selection.get("issues").get(0).get("mentions").get(0).get("evidence").get(0).deepCopy();
        span.put("evidence_id", "geo-synthetic"); geography.putArray("evidence").add(span);
        Files.write(root.resolve("source-pins.json"), "{}".getBytes());
        ObjectNode provenance = StrictJson.newObject(); provenance.put("schema", "zoop-legacy-export-provenance/1");
        ObjectNode retainedArticle = provenance.putArray("articles").addObject();
        retainedArticle.put("article_id", "a".repeat(64)); retainedArticle.put("article_version", version);
        retainedArticle.put("body_sha256", Canonical.sha256(selection.get("articles").get(0).get("record").get("body").asString()));
        retainedArticle.putArray("retained_input_record_hashes"); retainedArticle.putArray("retained_acquisition_content_hashes");
        Files.write(root.resolve("source-provenance.json"), Canonical.bytes(provenance));
        manifest = StrictJson.newObject(); manifest.put("schemaVersion", LegacyRealPackage.MANIFEST_SCHEMA);
        manifest.set("legacyOrigin", selection.get("origin")); manifest.putArray("selectedIssueIds").add("issue-synthetic-lab");
        manifest.putArray("selectionLedger").addObject().put("issueId", "issue-synthetic-lab").put("reason", "selected");
        ObjectNode binding = manifest.putArray("grantBindings").addObject(); binding.put("originalArticleId", "a".repeat(64));
        binding.put("originalArticleVersion", version); binding.put("sourceId", "synthetic-source"); binding.put("grantId", "synthetic-grant");
        binding.put("revision", "1"); binding.put("kind", "news");
        manifest.putArray("companyBindings").addObject().put("companyId", "SYNTHETIC:ACME")
                .put("originalName", "Synthetic Acme").put("canonicalName", "Synthetic Acme");
        saveSources(true);
        registry = new InMemoryDocumentRegistry(); graph = new InMemoryGraphHandoffRepository("previous", 1);
        graph.seedCompany("SYNTHETIC:ACME", "Synthetic Acme");
        TransactionOperations tx = new TransactionOperations() {
            @Override public <T> T execute(TransactionCallback<T> action) {
                if (afterAdmission != null) afterAdmission.run();
                return registry.transactionally(() -> graph.transactionally(() -> action.doInTransaction(null)));
            }
        };
        importer = new LegacyRealImporter(root, sources, ArtifactFileStore.at(artifacts), registry,
                new DocumentRegistrationService(registry, clock), graph, tx, clock);
    }

    private LegacyRealPackage.Request freeze() throws Exception {
        byte[] bundle = Canonical.appBytes(selection), geo = Canonical.bytes(geography);
        Files.write(root.resolve("bundle.json"), bundle); Files.write(root.resolve("geography.json"), geo);
        manifest.put("bundleDigest", Canonical.sha256(bundle)); manifest.put("geographyDigest", Canonical.sha256(geo));
        manifest.put("catalogueDigest", Canonical.digest(selection.get("companies")));
        manifest.put("ruleDefinitionsDigest", Canonical.digest(selection.get("enabled_rules")));
        manifest.put("sourcePinsDigest", Canonical.sha256("{}"));
        manifest.put("provenanceDigest", Canonical.sha256(Files.readAllBytes(root.resolve("source-provenance.json"))));
        ObjectNode sourceClaims = manifest.putObject("sourceInputDigests");
        sourceClaims.put("bundle.json", Canonical.sha256(bundle)); sourceClaims.put("geography.json", Canonical.sha256(geo));
        sourceClaims.put("source-pins.json", Canonical.sha256("{}"));
        sourceClaims.put("source-provenance.json", Canonical.sha256(Files.readAllBytes(root.resolve("source-provenance.json"))));
        if (metadataPolicy != null) {
            byte[] policy = Canonical.bytes(metadataPolicy);
            Files.write(root.resolve("metadata-policy.json"), policy);
            manifest.put("metadataPolicyDigest", Canonical.sha256(policy));
            sourceClaims.put("metadata-policy.json", Canonical.sha256(policy));
        }
        byte[] bytes = Canonical.bytes(manifest); Files.write(root.resolve("manifest.json"), bytes);
        String digest = Canonical.sha256(bytes);
        return new LegacyRealPackage.Request("legacy-real:" + digest, digest, Canonical.sha256(bundle), "synthetic-operator");
    }

    private void saveSources(boolean enabled) throws Exception {
        ObjectNode source = StrictJson.newObject(); source.put("sourceId", "synthetic-source"); source.put("adapter", "authored-files");
        source.put("inputRoot", root.toString()); source.putArray("allowedHosts").add("example.invalid");
        ObjectNode scope = source.putArray("scopes").addObject(); scope.put("scopeId", "synthetic"); scope.put("selection", "synthetic fixture");
        scope.putNull("initialCursor"); scope.putNull("articleXPath"); scope.putArray("timestampLimitations").add("authored fixture");
        ObjectNode grant = source.putObject("grant"); grant.put("grantId", "synthetic-grant"); grant.put("revision", "1");
        grant.put("sourceId", "synthetic-source"); grant.put("enabled", enabled); grant.put("rights", "known");
        grant.putArray("allowedOperations").add("read").add("store").add("quote-display"); grant.putArray("recipients"); grant.putArray("purposes");
        grant.putArray("evidence").add("owned authored synthetic fixture"); grant.putNull("expiresAt");
        ObjectNode current = StrictJson.newObject(); current.put("schemaVersion", "zoop-ingestion-s2-1"); current.put("revision", "synthetic-1");
        current.putArray("sources").add(source); Files.write(sources, Canonical.bytes(current));
    }

    @Test void stagesInactiveAndExactRetryPreservesRowsAndOriginalSpan() throws Exception {
        var request = freeze(); var result = importer.run(request);
        assertEquals("staged", result.get("outcome").asString());
        var before = graph.state(); assertEquals("unchanged", importer.run(request).get("outcome").asString()); assertEquals(before, graph.state());
        var projected = LegacyRealPackage.read(root, request); var issue = projected.graph().issues().getFirst();
        assertEquals("Synthetic Acme lab", issue.label()); assertEquals("domestic", issue.geography());
        assertEquals(1, projected.graph().relations().size()); assertEquals("previous", graph.activeVersionId); assertEquals(1, graph.activations);
        var evidence = graph.evidenceRows().values().iterator().next();
        assertEquals(2, evidence.startOffset()); assertEquals(42, evidence.endOffset()); assertEquals("Acme opened a lab in Seoul, South Korea.", evidence.quote());
        assertTrue(evidence.id().matches("ev-[0-9a-f]{64}")); assertNull(registry.findArticle(evidence.articleId()).orElseThrow().currentVersion());
        assertEquals("not-performed", StrictJson.parseObject(projected.receipt()).object("appVerification").string("nativeProvenance"));
        assertEquals(request.migrationId(), graph.sources(projected.versionId()).getFirst().handoffId());
    }

    private void explicitMetadata() {
        manifest.put("schemaVersion", LegacyRealPackage.METADATA_MANIFEST_SCHEMA);
        selection.put("selection_basis", "selected-bound-article-and-metadata-policy");
        ObjectNode audit = (ObjectNode) selection.get("candidate_audit").get(0);
        audit.put("source_audit_record_sha256", Canonical.sha256(Canonical.appBytes(audit)));
        metadataPolicy = StrictJson.newObject();
        metadataPolicy.put("schemaVersion", "zoop-legacy-metadata-policy-1"); metadataPolicy.put("policyVersion", LegacyRealPackage.METADATA_POLICY);
        ObjectNode item = metadataPolicy.putArray("issues").addObject();
        item.put("issueId", "issue-synthetic-lab"); item.putArray("sourceAuditDigests").add(audit.get("source_audit_record_sha256").asString());
        item.putObject("geography").put("mode", "unknown").put("reasonCode", "not-supported");
        item.putObject("eventTime").put("mode", "preserve"); item.putObject("period").put("mode", "preserve");
        item.put("decisionRef", "synthetic-metadata-review"); item.put("decisionVersion", "1");
    }

    @Test void legacy3UnknownPreservesOriginalAndPinsPolicyThroughInactiveImport() throws Exception {
        explicitMetadata();
        var request = freeze();
        var projection = LegacyRealPackage.read(root, request);
        assertEquals(4, projection.graph().snapshotFormat());
        assertTrue(projection.graph().issues().getFirst().hasExplicitUnknownGeography());
        assertEquals("2026-01-01", projection.graph().issues().getFirst().eventTime());
        assertEquals("staged", importer.run(request).get("outcome").asString());
        assertEquals("unchanged", importer.run(request).get("outcome").asString());
        var receipt = StrictJson.parseObject(projection.receipt());
        assertEquals("zoop-legacy-real-import-receipt-3", receipt.string("schemaVersion"));
        assertEquals(metadataPolicy, receipt.object("legacyProvenance").raw("metadataPolicy"));
        assertEquals(List.of("KR"), receipt.object("legacyProvenance").objects("candidate_audit").getFirst()
                .object("original_mention").strings("countries"));
        assertEquals("previous", graph.activeVersionId);
        Files.writeString(root.resolve("metadata-policy.json"), "{}");
        assertEquals("package_pin_conflict", assertThrows(LegacyRealPackage.Invalid.class, () -> importer.run(request)).getMessage());
    }

    @Test void metadataOnlyHoldRequiresPositiveStructuredCoreProofAndPreservesHold() throws Exception {
        ObjectNode audit = (ObjectNode) selection.get("candidate_audit").get(0);
        audit.put("status", "HOLD");
        ObjectNode validation = (ObjectNode) audit.get("validation");
        ((ObjectNode) validation.get("verdicts").get(0)).put("decision", "HOLD").put("reason", "field-only uncertainty");
        ObjectNode verdict = validation.putArray("field_verdicts").addObject();
        verdict.put("field", "countries").put("decision", "HOLD").put("reason", "field-only uncertainty");
        ObjectNode issue = (ObjectNode) selection.get("issues").get(0);
        ObjectNode field = issue.putArray("field_decisions").addObject();
        field.put("candidate_id", "candidate-synthetic-lab").put("mention_id", "m1");
        field.putArray("outcomes").add(verdict.deepCopy());
        ((ObjectNode) issue.get("mentions").get(0)).remove("countries");
        ObjectNode trace = validation.putObject("trace");
        trace.put("contract_version", "a".repeat(64)).put("model", "synthetic-original-verifier").put("provider", "authored");
        trace.putObject("decision_policy").put("support_min", 0.65).put("contradiction_max", 0.1).put("reject_min", 0.9);
        var observations = trace.putArray("observations");
        for (String check : List.of("concrete_event", "title", "event_type", "action", "assertion_status", "background",
                "target", "participant_identity:0", "participant_role:0", "INVOLVES", "relation-assertion", "country:0")) {
            boolean unknown = check.equals("country:0");
            String target = unknown ? "field:countries"
                    : ("INVOLVES".equals(check) || "relation-assertion".equals(check)) ? "relation-synthetic-lab" : "issue";
            ObjectNode observation = observations.addObject();
            observation.put("target", target).put("check", check.equals("relation-assertion") ? "assertion_status" : check)
                    .put("choice", unknown ? "INSUFFICIENT" : "SUPPORTED").put("confidence", unknown ? 0.8 : 0.99).put("question_id", check);
            observation.putObject("probabilities").put("SUPPORTED", unknown ? 0.2 : 0.99).put("INSUFFICIENT", unknown ? 0.8 : 0.01).put("CONTRADICTED", 0.0);
        }
        explicitMetadata();
        var request = freeze();
        var projected = LegacyRealPackage.read(root, request);
        assertEquals("HOLD", StrictJson.parseObject(projected.receipt()).object("legacyProvenance").objects("candidate_audit").getFirst().string("status"));
        assertEquals("metadata-policy:legacy-real-projection-3", projected.bundle().objects("issues").getFirst().string("approvalBasis"));
        assertTrue(projected.graph().issues().getFirst().hasExplicitUnknownGeography());
        ObjectNode actionProof = (ObjectNode) observations.get(3);
        ((ObjectNode) actionProof.get("probabilities")).put("SUPPORTED", 0.2).put("INSUFFICIENT", 0.8);
        assertThrows(LegacyRealPackage.Invalid.class, () -> LegacyRealPackage.read(root, freeze()));
        validation.remove("trace");
        assertThrows(LegacyRealPackage.Invalid.class, () -> LegacyRealPackage.read(root, freeze()));
    }


    @Test void recognizedSameIdAliasProjectsPinnedNameAndPreservesOriginalAcrossRetries() throws Exception {
        ((ObjectNode) manifest.get("companyBindings").get(0)).put("canonicalName", "Canonical Acme");
        graph.seedCompany("SYNTHETIC:ACME", "Canonical Acme", "Synthetic Acme");
        var request = freeze();
        var projection = LegacyRealPackage.read(root, request);
        assertEquals("Canonical Acme", projection.graph().companies().getFirst().label());
        assertEquals("Canonical Acme", projection.bundle().objects("companies").getFirst().string("label"));
        assertEquals(selection.get("companies"), StrictJson.parseObject(projection.receipt()).object("legacyProvenance").raw("companies"));
        assertEquals("staged", importer.run(request).get("outcome").asString());
        var state = registry.state();
        assertEquals("unchanged", importer.run(request).get("outcome").asString());
        assertEquals(state, registry.state());
        assertArrayEquals(projection.receipt(), LegacyRealPackage.read(root, request).receipt());
        assertArrayEquals(projection.snapshot(), LegacyRealPackage.read(root, request).snapshot());
        for (String canonical : List.of("Renamed Acme", "Canonical Acme")) {
            graph.seedCompany("SYNTHETIC:ACME", canonical);
            assertEquals("company_mismatch", importer.run(request).get("code").asString());
            assertEquals(state, registry.state());
            assertEquals(1, graph.state().versions().size());
        }
    }

    @Test void aliasOnAnotherIdAndIncomingOnlyAliasCannotAuthorizeBinding() throws Exception {
        ((ObjectNode) manifest.get("companyBindings").get(0)).put("canonicalName", "Canonical Acme");
        graph.seedCompany("SYNTHETIC:ACME", "Canonical Acme");
        graph.seedCompany("SYNTHETIC:OTHER", "Other company", "Synthetic Acme");
        var request = freeze();
        assertEquals("company_mismatch", importer.run(request).get("code").asString());
        ((ObjectNode) manifest.get("companyBindings").get(0)).putArray("aliases").add("Synthetic Acme");
        assertThrows(StrictJson.Malformed.class, () -> importer.run(freeze()));
        assertEquals(0, graph.state().versions().size());
        assertEquals(0, registry.state().articles().size());
    }

    @Test void canonicalChangeBeforeLockRejectsPinnedProjection() throws Exception {
        var request = freeze();
        afterAdmission = () -> graph.seedCompany("SYNTHETIC:ACME", "Changed canonical", "Synthetic Acme");
        assertEquals("company_mismatch", importer.run(request).get("code").asString());
        assertEquals(0, graph.state().versions().size());
        assertEquals(0, registry.state().articles().size());
    }

    @Test void companyBindingsMustCloseExactlyOverOriginalCompanies() throws Exception {
        var original = manifest.get("companyBindings").deepCopy();
        for (String fault : List.of("missing", "duplicate", "extra", "wrong-original", "blank")) {
            manifest.set("companyBindings", original.deepCopy());
            var bindings = (tools.jackson.databind.node.ArrayNode) manifest.get("companyBindings");
            switch (fault) {
                case "missing" -> bindings.remove(0);
                case "duplicate" -> bindings.add(bindings.get(0).deepCopy());
                case "extra" -> bindings.addObject().put("companyId", "SYNTHETIC:OTHER")
                        .put("originalName", "Other").put("canonicalName", "Other");
                case "wrong-original" -> ((ObjectNode) bindings.get(0)).put("originalName", "Forged");
                case "blank" -> ((ObjectNode) bindings.get(0)).put("canonicalName", " ");
            }
            assertThrows(LegacyRealPackage.Invalid.class, () -> importer.run(freeze()), fault);
        }
        assertEquals(0, graph.state().versions().size());
    }

    @Test void editedMappingNeedsNewPinsAndRefreezingCreatesANewVersion() throws Exception {
        var first = freeze();
        assertEquals("staged", importer.run(first).get("outcome").asString());
        ((ObjectNode) manifest.get("companyBindings").get(0)).put("canonicalName", "Canonical Acme");
        graph.seedCompany("SYNTHETIC:ACME", "Canonical Acme", "Synthetic Acme");
        var second = freeze();
        assertEquals("manifest_pin_conflict", assertThrows(LegacyRealPackage.Invalid.class, () -> importer.run(first)).getMessage());
        assertNotEquals(first.migrationId(), second.migrationId());
        assertEquals("staged", importer.run(second).get("outcome").asString());
        assertEquals(2, graph.state().versions().size());
    }

    @Test void changedPinsAndForgedContentAreRefusedBeforeStaging() throws Exception {
        var request = freeze(); byte[] original = Files.readAllBytes(root.resolve("bundle.json"));
        Files.writeString(root.resolve("bundle.json"), "{}");
        assertEquals("package_pin_conflict", assertThrows(LegacyRealPackage.Invalid.class, () -> importer.run(request)).getMessage());
        Files.write(root.resolve("bundle.json"), original);
        ObjectNode span = (ObjectNode) selection.get("issues").get(0).get("mentions").get(0).get("evidence").get(0);
        span.put("quote", "invented");
        ((ObjectNode) selection.get("candidate_audit").get(0)).set("original_mention", selection.get("issues").get(0).get("mentions").get(0).deepCopy());
        var forged = freeze();
        assertEquals("quote_mismatch", assertThrows(LegacyRealPackage.Invalid.class, () -> importer.run(forged)).getMessage());
        assertEquals(0, graph.state().versions().size());
    }

    @Test void pinnedUnselectedArticleIsStillRejectedByExportClosure() throws Exception {
        ObjectNode article = (ObjectNode) selection.get("articles").get(0).deepCopy();
        ((ObjectNode) article.get("record")).put("body", "Unbound private body");
        ((ObjectNode) article.get("record")).put("article_id", "b".repeat(64));
        ObjectNode raw = (ObjectNode) article.get("record").deepCopy(); raw.remove("collected_at");
        article.put("article_version", Canonical.digest(raw));
        ((tools.jackson.databind.node.ArrayNode) selection.get("articles")).add(article);
        var request = freeze();
        assertEquals("article_export_closure", assertThrows(LegacyRealPackage.Invalid.class, () -> importer.run(request)).getMessage());
        assertEquals(0, graph.state().versions().size());
    }
    @Test void pinnedOriginAndProvenanceCannotCarryUnapprovedMetadata() throws Exception {
        ((ObjectNode) selection.get("origin").get("snapshot")).put("reason", "private unbound quote");
        assertThrows(StrictJson.Malformed.class, () -> importer.run(freeze()));
        ((ObjectNode) selection.get("origin").get("snapshot")).remove("reason");
        ObjectNode provenance = (ObjectNode) StrictJson.parseObject(Files.readAllBytes(root.resolve("source-provenance.json"))).node();
        ((ObjectNode) provenance.get("articles").get(0)).put("note", "private unbound quote");
        Files.write(root.resolve("source-provenance.json"), Canonical.bytes(provenance));
        assertThrows(StrictJson.Malformed.class, () -> importer.run(freeze()));
        assertEquals(0, graph.state().versions().size());
    }

    @Test void graphSkippedRelationsRejectForeignArticleEvidenceBeforeReceipt() throws Exception {
        ObjectNode issue = (ObjectNode) selection.get("issues").get(0);
        var relations = (tools.jackson.databind.node.ArrayNode) issue.get("relations");
        for (String type : List.of("REPORTS", "PROVIDES_BACKGROUND", "FOLLOWS")) {
            ObjectNode relation = (ObjectNode) relations.get(0).deepCopy();
            relation.put("relation_type", type); relation.put("relation_id", "relation-foreign");
            relation.put("source", "FOLLOWS".equals(type) ? "issue-synthetic-lab" : "a".repeat(64));
            relation.put("target", "FOLLOWS".equals(type) ? "issue-unselected" : "issue-synthetic-lab");
            relation.putArray("evidence").addObject().put("article_id", "b".repeat(64))
                    .put("article_version", "0".repeat(64)).put("start", 0).put("end", 7).put("quote", "private");
            relations.add(relation);
            assertEquals("relation_evidence_reference", assertThrows(LegacyRealPackage.Invalid.class, () -> importer.run(freeze())).getMessage());
            relations.remove(relations.size() - 1);
        }
        assertEquals(0, graph.state().versions().size());
    }


    @Test void currentRightsAndCatalogueRemainIndependentGates() throws Exception {
        var request = freeze(); saveSources(false);
        assertEquals("current_grant_source_rights_unknown_or_denied", importer.run(request).get("code").asString());
        assertEquals(0, graph.state().versions().size()); saveSources(true);
        graph.seedCompany("SYNTHETIC:ACME", "Another identity");
        assertEquals("company_mismatch", importer.run(request).get("code").asString());
        assertEquals(0, graph.state().versions().size());
    }

    @Test void geographyCannotBeChangedToAnUnmentionedCountry() throws Exception {
        ObjectNode decision = (ObjectNode) geography.get("records").get(0);
        decision.putArray("country_codes").add("US"); decision.put("classification", "international");
        var request = freeze();
        assertEquals("geography_literal_missing", assertThrows(LegacyRealPackage.Invalid.class, () -> importer.run(request)).getMessage());
    }

    @Test void rightsChangedAfterAdmissionRollBackAllRowsAndOwnedFiles() throws Exception {
        var request = freeze();
        ObjectNode denied = (ObjectNode) StrictJson.parseObject(Files.readAllBytes(sources)).node();
        ((ObjectNode) denied.get("sources").get(0).get("grant")).put("enabled", false);
        afterAdmission = () -> {
            try { Files.write(sources, Canonical.bytes(denied)); }
            catch (java.io.IOException error) { throw new java.io.UncheckedIOException(error); }
        };
        assertEquals("current_grant_source_rights_unknown_or_denied", importer.run(request).get("code").asString());
        assertEquals(0, registry.state().articles().size());
        assertEquals(0, graph.state().versions().size());
        try (var files = Files.walk(artifacts)) {
            assertEquals(List.of(".document-import.lock"), files.filter(Files::isRegularFile)
                    .map(p -> p.getFileName().toString()).toList());
        }
    }

    @Test void retainedR1ReleaseKeepsItsRoleMaskAndTruthfulApproval() throws Exception {
        ObjectNode audit = (ObjectNode) selection.get("candidate_audit").get(0);
        audit.put("status", "HOLD");
        ((ObjectNode) audit.get("original_mention").get("participants").get(0)).put("role", "unconfirmed operator");
        ((ObjectNode) selection.get("issues").get(0).get("mentions").get(0).get("participants").get(0)).put("role_unconfirmed", true);
        ObjectNode verdict = (ObjectNode) audit.get("validation").get("verdicts").get(0);
        verdict.put("decision", "HOLD"); verdict.put("reason", "Support or contradiction probability requires review: participant_role:0");
        ObjectNode resolution = audit.putObject("publication_resolution");
        resolution.put("type", "existing_enabled_publication_rule"); resolution.put("rule_id", "R1@2");
        ObjectNode effect = resolution.putObject("effect"); effect.putArray("participants").add(0);
        effect.putArray("relations"); effect.putArray("dropped");
        selection.putArray("enabled_rules").addObject().put("id", "R1@2");
        var request = freeze();
        assertEquals("staged", importer.run(request).get("outcome").asString());
        Obj issue = LegacyRealPackage.read(root, request).bundle().objects("issues").getFirst();
        assertEquals("review-rule:R1@2", issue.string("approvalBasis"));
        assertNull(issue.objects("mentions").getFirst().objects("participants").getFirst().stringOrNull("role"));
    }

    @Test void unlinkedNamedParticipantKeepsItsTextWithoutInventingACatalogueCompany() throws Exception {
        var mention = (ObjectNode) selection.get("issues").get(0).get("mentions").get(0);
        var participants = (tools.jackson.databind.node.ArrayNode) mention.get("participants");
        participants.addObject().put("company_id", "NASDAQ:OTHER").put("name", "Quoted other participant").putNull("role");
        ((ObjectNode) selection.get("candidate_audit").get(0)).set("original_mention", mention.deepCopy());
        var projection = LegacyRealPackage.read(root, freeze());
        var participant = projection.bundle().objects("issues").getFirst().objects("mentions").getFirst().objects("participants").get(1);
        assertNull(participant.stringOrNull("companyId"));
        assertEquals("Quoted other participant", participant.string("name"));
        assertEquals(1, projection.graph().companies().size());
    }

    @Test void aRelationCanCiteItsOwnExactSpanOfTheIssuesPinnedArticle() throws Exception {
        var span = (ObjectNode) selection.get("issues").get(0).get("relations").get(0).get("evidence").get(0);
        span.put("start", 23); span.put("quote", "Seoul, South Korea.");
        var projection = LegacyRealPackage.read(root, freeze());
        assertEquals(2, projection.evidence().size());
        assertEquals(2, projection.graph().issues().getFirst().evidenceIds().size());
        assertEquals("Seoul, South Korea.", projection.evidence().get(1).string("quote"));
    }
}
