package com.zoop.graph.importer;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.time.Duration;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.Base64;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import java.util.stream.Collectors;
import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.common.json.Canonical;
import com.zoop.document.analysis.repository.JdbcDocumentAnalysisRepository;
import com.zoop.document.evidence.service.DocumentReadSources;
import com.zoop.document.importer.IngestionExportParser;
import com.zoop.document.repository.ArtifactRow;
import com.zoop.document.repository.JdbcDocumentRegistryRepository;
import com.zoop.document.repository.VersionRow;
import com.zoop.graph.publication.GraphPublicationAuthority;
import com.zoop.graph.publication.GraphPublicationComposer;
import com.zoop.graph.publication.GraphPublicationPreparer;
import com.zoop.graph.publication.GraphRoundPreparer;
import com.zoop.graph.publication.JdbcGraphPublicationPreparationRepository;
import com.zoop.graph.publication.GraphPublicationReader;
import com.zoop.graph.publication.JdbcGraphPublicationRepository;
import com.zoop.graph.publication.PublicationComposeRequest;
import com.zoop.graph.publication.PublicationMerger;
import com.zoop.graph.read.DisclosureExclusions;
import com.zoop.graph.round.JdbcGraphRoundImportLock;
import com.zoop.graph.round.JdbcGraphRoundRepository;
import com.zoop.graph.version.JdbcGraphVersionRepository;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.node.ObjectNode;
import static org.junit.jupiter.api.Assertions.*;

/** The automatic preparation (#55) against real migrations, importer, composer and publication reader. */
@Tag("graph-postgres")
class GraphPublicationPreparePostgresTest {
    private static final Instant NOW = Instant.parse("2026-11-02T01:02:03Z");
    private static final Clock CLOCK = Clock.fixed(NOW, ZoneOffset.UTC);
    @TempDir Path temp;
    private String schema;
    private JdbcTemplate jdbc;
    private JdbcDocumentRegistryRepository registry;
    private JdbcGraphHandoffRepository graph;
    private JdbcGraphVersionRepository versions;
    private JdbcGraphPublicationRepository publications;
    private TransactionTemplate transaction;
    private DriverManagerDataSource dataSource;
    private NamedParameterJdbcTemplate named;
    private int slots;
    private ArtifactFileStore files;
    private Path authority;

    @BeforeEach void start() throws Exception {
        schema = "prepare_" + UUID.randomUUID().toString().replace("-", "");
        String url = System.getenv("ZOOP_COMPANY_TEST_DB_URL");
        if (url == null || !url.matches("jdbc:postgresql://127\\.0\\.0\\.1:[0-9]+/zoop_company_test_19")) {
            throw new IllegalStateException("Set ZOOP_COMPANY_TEST_DB_URL to the dedicated localhost zoop_company_test_19 database");
        }
        dataSource = new DriverManagerDataSource(url + "?currentSchema=" + schema + ",public", "company_test",
                System.getenv().getOrDefault("ZOOP_COMPANY_TEST_DB_PASSWORD", ""));
        jdbc = new JdbcTemplate(dataSource);
        jdbc.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public");
        jdbc.execute("CREATE EXTENSION IF NOT EXISTS btree_gist WITH SCHEMA public");
        Flyway.configure().dataSource(dataSource).schemas(schema).defaultSchema(schema).load().migrate();
        named = new NamedParameterJdbcTemplate(jdbc);
        registry = new JdbcDocumentRegistryRepository(named);
        graph = new JdbcGraphHandoffRepository(named, new JdbcDocumentAnalysisRepository(named));
        versions = new JdbcGraphVersionRepository(named, CLOCK);
        publications = new JdbcGraphPublicationRepository(named);
        transaction = new TransactionTemplate(new DataSourceTransactionManager(dataSource));
        transaction.setTimeout(300);
        jdbc.update("INSERT INTO companies (id, name, name_key, search_text) VALUES (?, ?, '', ''), (?, ?, '', '')",
                HandoffFixtures.COMPANY_A, "합성기업", HandoffFixtures.COMPANY_B, "합성부품");
        files = ArtifactFileStore.at(Files.createDirectory(temp.toRealPath().resolve("producer")));
        authority = temp.toRealPath().resolve("authority.json");
        Files.writeString(authority, """
                {"schemaVersion":"zoop-ingestion-s2-1","revision":"registry-a","sources":[{
                  "sourceId":"synthetic-source","adapter":"authored-files","inputRoot":"/synthetic",
                  "allowedHosts":["example.invalid"],"scopes":[{"scopeId":"scope-a","selection":"all",
                    "initialCursor":null,"articleXPath":null,"timestampLimitations":["synthetic"]}],
                  "grant":{"grantId":"operator-grant","revision":"rights-1","sourceId":"synthetic-source","enabled":true,
                    "rights":"known","allowedOperations":["read","store","quote-display"],"recipients":[],
                    "purposes":[],"evidence":["synthetic operator grant"],"expiresAt":null}}]}
                """);
        byte[] text = HandoffFixtures.TEXT.getBytes(StandardCharsets.UTF_8);
        String textId = "text-" + HandoffFixtures.ARTICLE_VERSION;
        try (var session = files.open()) {
            var stored = session.put("extracted_text", textId + ".txt", text);
            transaction.executeWithoutResult(status -> {
                registry.insertArticleIfAbsent(HandoffFixtures.ARTICLE_ID, "news", HandoffFixtures.SOURCE, NOW);
                registry.insertArtifactIfAbsent(new ArtifactRow(textId, "extracted_text", stored.uri(), stored.sha256(), stored.bytes(), "text/plain; charset=utf-8", NOW));
                registry.insertVersionIfAbsent(new VersionRow(HandoffFixtures.ARTICLE_ID, HandoffFixtures.ARTICLE_VERSION, "합성 제목", null,
                        "https://example.invalid/a", Instant.parse("2026-10-08T00:00:00Z"), null, "datetime", null, textId,
                        Instant.parse("2026-10-14T01:02:03.456789Z")));
            });
        }
    }

    @AfterEach void stop() {
        if (jdbc != null) jdbc.execute("DROP SCHEMA IF EXISTS " + schema + " CASCADE");
    }

    @Test void theFirstPublicationStaysAnOperatorCompose() {
        var result = preparer().run();
        assertEquals("failed", result.get("status").asString());
        assertEquals("first_publication_manual", result.get("code").asString());
    }

    @Test void aChangedValueStopsWithItsChangesAndNoCandidate() {
        String base = importNative(HandoffFixtures.Spec.standard());
        String published = publish(base);
        String incoming = importNative(HandoffFixtures.Spec.standard().withEvent("2026-10-01", "day"));

        var result = preparer().run();
        assertEquals("failed", result.get("status").asString(), result.toString());
        assertEquals("correction_required", result.get("code").asString());
        assertEquals(List.of(incoming), strings(result, "incomingVersionIds"));
        var eventTime = change(result, "eventTime");
        assertEquals("issue", eventTime.get("kind").asString());
        assertEquals(Set.of(base + ":base", incoming + ":incoming"), eventTime.get("values").values().stream()
                .map(v -> v.get("sourceVersionId").asString() + ":" + v.get("side").asString()).collect(Collectors.toSet()));
        // The fixed inputs are kept for the operator decision that follows.
        var request = PublicationComposeRequest.parse(Canonical.bytes(result.get("request")));
        assertEquals(Canonical.sha256(decisionBytes(result)), request.decisionsSha256());
        assertEquals(request.decisionsSha256(), result.get("decisionsSha256").asString());
        // The preparation's operator name cannot carry these inputs into an operator compose: a change is left to people.
        assertFalse(GraphPublicationPreparer.proposes(reader(), publications, request, decisionBytes(result)));
        // Under the reserved name the guard refuses it; without the guard the composer would answer correction_required.
        assertEquals("request_invalid", GraphPublicationPreparer.operatorCompose(reader(), publications, composer(), request,
                decisionBytes(result)).get("code").asString());
        assertEquals(published, versions.active().orElseThrow().id());
        assertEquals(0, (int) jdbc.queryForObject("SELECT count(*) FROM graph_publications WHERE base_version_id = ?", Integer.class, published));
    }

    @Test void anAgreeingSourceIsStagedAndItsKeptInputsRecoverAsAnOperatorCompose() {
        String published = publish(importNative(HandoffFixtures.Spec.standard()));
        String incoming = importNative(HandoffFixtures.Spec.standard());

        var result = preparer().run();
        assertEquals("succeeded", result.get("status").asString(), result.toString());
        assertEquals("staged", result.get("outcome").asString());
        assertEquals(List.of(incoming), strings(result, "incomingVersionIds"));
        assertEquals(0, result.get("changes").size());
        String candidate = result.get("graphVersionId").asString();
        var publication = reader().read(candidate);
        assertEquals(published, publication.baseVersionId());
        assertEquals(published, versions.active().orElseThrow().id());
        assertFalse(versions.everActivated(candidate));
        assertEquals(2, publication.contributions().size());

        // Recovery of an unknown outcome: the kept request and decision bytes, run as an operator compose, find the committed candidate.
        var request = PublicationComposeRequest.parse(Canonical.bytes(result.get("request")));
        assertEquals(GraphPublicationPreparer.OPERATOR, request.operator());
        assertTrue(GraphPublicationPreparer.proposes(reader(), publications, request, decisionBytes(result)));
        assertFalse(GraphPublicationPreparer.proposes(reader(), publications, request, "{}".getBytes(StandardCharsets.UTF_8)));
        var recovered = GraphPublicationPreparer.operatorCompose(reader(), publications, composer(), request, decisionBytes(result));
        assertEquals("unchanged", recovered.get("outcome").asString(), recovered.toString());
        assertEquals(candidate, recovered.get("graphVersionId").asString());
        var again = preparer().run();
        assertEquals("unchanged", again.get("outcome").asString(), again.toString());
        assertEquals(candidate, again.get("graphVersionId").asString());

        // A preparation after a new import is a new composition, not a recovery of the first one.
        String later = importNative(HandoffFixtures.Spec.standard());
        var next = preparer().run();
        assertEquals("staged", next.get("outcome").asString(), next.toString());
        assertEquals(Set.of(incoming, later), Set.copyOf(strings(next, "incomingVersionIds")));
        assertNotEquals(candidate, next.get("graphVersionId").asString());
        assertEquals(List.of(candidate), strings(next, "pendingCandidates"));
    }

    @Test void aLabelCorrectionWithoutNewSourcesIsStagedOnTheBaseAndReadBackAndInherited() {
        String published = publish(importNative(HandoffFixtures.Spec.standard()));
        var base = reader().read(published);
        var source = base.contributions().getFirst();
        var issue = base.snapshot().issues().getFirst();
        ObjectNode decisions = (ObjectNode) PublicationMerger.emptyDecisions().node().deepCopy();
        decisions.put("schemaVersion", PublicationMerger.DECISIONS_SCHEMA_2);
        var correction = decisions.putArray(PublicationMerger.LABEL_CORRECTIONS).addObject();
        correction.put("issueId", issue.issueId()); correction.put("expectedLabelDigest", Canonical.digest(PublicationMerger.field(issue, "label")));
        correction.put("label", "교정한 사건명");
        var evidence = correction.putArray("evidenceRefs").addObject();
        evidence.put("sourceVersionId", source.sourceVersionId()); evidence.put("issueId", issue.issueId()); evidence.put("evidenceId", issue.evidenceIds().getFirst());
        correction.put("reviewer", "operator"); correction.put("decisionRef", "label-review"); correction.put("decisionVersion", "2026-11-04");
        byte[] bytes = Canonical.bytes(decisions);
        var state = graph.publicationState();
        String basePin = registry.findArtifact("artifact-receipt-" + published).orElseThrow().sha256();
        var request = new PublicationComposeRequest(published, List.of(), published, basePin, java.util.Map.of(), state.ruleRevision(),
                state.reviewRevision(), Canonical.sha256(bytes), "synthetic");
        assertEquals(request, PublicationComposeRequest.parse(Canonical.bytes(request.wire())));

        var composed = GraphPublicationPreparer.operatorCompose(reader(), publications, composer(), request, bytes);
        assertEquals("succeeded", composed.get("status").asString(), composed.toString());
        assertEquals("staged", composed.get("outcome").asString());
        assertEquals(List.of(), strings(composed, "incomingVersionIds"));
        assertEquals(1, composed.get("counts").get("labelCorrections").asInt());
        assertEquals(base.snapshot().issues().size(), composed.get("counts").get("issues").asInt());
        String candidate = composed.get("graphVersionId").asString();
        assertNotEquals(published, candidate);
        // The reader re-merges the stored decisions and owners: only the name differs from the base.
        var publication = reader().read(candidate);
        assertEquals(published, publication.baseVersionId());
        assertEquals(base.contributions().size(), publication.contributions().size());
        assertEquals(base.issueSources(), publication.issueSources());
        assertEquals(base.snapshot().relations(), publication.snapshot().relations());
        ObjectNode expected = (ObjectNode) GraphPublicationReader.json(issue); expected.put("label", "교정한 사건명");
        assertEquals(expected, GraphPublicationReader.json(publication.snapshot().issues().getFirst()));
        assertEquals(PublicationMerger.DECISIONS_SCHEMA_2, publication.effectiveDecisions().string("schemaVersion"));
        assertFalse(versions.everActivated(candidate));
        assertEquals(published, versions.active().orElseThrow().id());
        var again = GraphPublicationPreparer.operatorCompose(reader(), publications, composer(), request, bytes);
        assertEquals("unchanged", again.get("outcome").asString(), again.toString());
        assertEquals(candidate, again.get("graphVersionId").asString());

        // Without new sources the request must change the base's decisions, and the reserved operator never takes this path.
        byte[] none = Canonical.bytes(PublicationMerger.emptyDecisions().node());
        var undecided = new PublicationComposeRequest(published, List.of(), published, basePin, java.util.Map.of(), state.ruleRevision(),
                state.reviewRevision(), Canonical.sha256(none), "synthetic");
        assertEquals("request_invalid", composer().run(undecided, none).get("code").asString());
        assertFalse(GraphPublicationPreparer.proposes(reader(), publications, request, bytes));
        assertEquals("nothing_to_prepare", preparer().run().get("outcome").asString());

        // Once the correction is public, a later import is prepared on it: the same-headline selection keeps the owner and the name is inherited.
        activate(candidate);
        String candidatePin = registry.findArtifact("artifact-receipt-" + candidate).orElseThrow().sha256();
        var repeated = new PublicationComposeRequest(candidate, List.of(), candidate, candidatePin, java.util.Map.of(), state.ruleRevision(),
                state.reviewRevision(), Canonical.sha256(bytes), "synthetic");
        assertEquals("request_invalid", composer().run(repeated, bytes).get("code").asString());
        String incoming = importNative(HandoffFixtures.Spec.standard());
        var next = preparer().run();
        assertEquals("staged", next.get("outcome").asString(), next.toString());
        assertEquals(List.of(incoming), strings(next, "incomingVersionIds"));
        assertEquals(0, next.get("changes").size());
        var inherited = reader().read(next.get("graphVersionId").asString());
        assertEquals(candidate, inherited.baseVersionId());
        assertEquals("교정한 사건명", inherited.snapshot().issues().getFirst().label());
        assertEquals(1, PublicationMerger.labelCorrections(inherited.effectiveDecisions()).size());
        // The fixture's second import repeats the issue record exactly, so no same-headline selection is needed (PublicationMergerTest
        // covers the record that only adds evidence); any selection the preparation did write names the owner's source value.
        for (var selection : inherited.effectiveDecisions().objects("fieldSelections")) {
            assertEquals(PublicationMerger.AUTO_REVIEWER, selection.string("reviewer"));
            assertEquals(Canonical.digest(PublicationMerger.field(source.projection().issues().getFirst(), "label")), selection.string("expectedValueDigest"));
        }
        assertEquals(source.issueRef(issue.issueId()), inherited.issueSources().get(issue.issueId()).headlineSources().get("label"));
        assertEquals(2, inherited.contributions().size());
    }

    @Test void nothingToPrepareWithoutNewImportsAndASourceLeftOutOfAnOperatorComposeStaysOut() {
        // Imported before the operator composed the published version: the operator chose not to include it.
        importNative(HandoffFixtures.Spec.standard().withEvent("2026-10-01", "day"));
        publish(importNative(HandoffFixtures.Spec.standard()));
        var result = preparer().run();
        assertEquals("nothing_to_prepare", result.get("outcome").asString(), result.toString());
        assertEquals(List.of(), strings(result, "incomingVersionIds"));
    }

    @Test void aSourceImportedWhileACandidateWaitsForApprovalIsPreparedAfterIt() {
        publish(importNative(HandoffFixtures.Spec.standard()));
        String first = importNative(HandoffFixtures.Spec.standard());
        String candidate = preparer().run().get("graphVersionId").asString();
        String waiting = importNative(HandoffFixtures.Spec.standard());
        // Until the first candidate is published, a run prepares on the same base and admits both sources together.
        assertEquals(Set.of(first, waiting), Set.copyOf(strings(preparer().run(), "incomingVersionIds")));
        activate(candidate);
        var result = preparer().run();
        assertEquals("staged", result.get("outcome").asString(), result.toString());
        assertEquals(List.of(waiting), strings(result, "incomingVersionIds"));
    }

    @Test void aSourceImportedWhileAnOperatorComposedIsStillPrepared() {
        String published = publish(importNative(HandoffFixtures.Spec.standard()));
        String chosen = importNative(HandoffFixtures.Spec.standard());
        String meanwhile = importNative(HandoffFixtures.Spec.standard());
        // The operator's request names only the first source; the composition commits after the second one was imported.
        String composed = compose(published, chosen);
        activate(composed);
        var result = preparer().run();
        assertEquals("staged", result.get("outcome").asString(), result.toString());
        assertEquals(List.of(meanwhile), strings(result, "incomingVersionIds"));
    }

    @Test void aFixtureActiveVersionStaysAnOperatorCompose() {
        importNative(HandoffFixtures.Spec.standard());
        var at = Timestamp.from(NOW);
        jdbc.update("""
                INSERT INTO artifacts (id, kind, storage_uri, sha256, bytes, media_type, created_at)
                VALUES ('artifact-fixture-prepare', 'graph_snapshot', 'fixture:prepare.json', ?, 1, 'application/json', ?)
                """, "f".repeat(64), at);
        jdbc.update("""
                INSERT INTO graph_versions (id, sequence, kind, created_at, published_at, created_by, reason, source_label,
                    issue_count, relation_count, article_count, snapshot_artifact_id, review_revision, active)
                VALUES ('fixture-prepare', (SELECT COALESCE(MAX(sequence), 0) + 1 FROM graph_versions), 'fixture', ?, ?, 'system',
                    'synthetic', 'fixture', 0, 0, 0, 'artifact-fixture-prepare', 0, true)
                """, at, at);
        var result = preparer().run();
        assertEquals("first_publication_manual", result.get("code").asString(), result.toString());
        assertEquals("fixture-prepare", result.get("activeVersionId").asString());
    }

    @Test void aKeptRequestReturnsAConflictOnceTheActiveVersionMoved() {
        publish(importNative(HandoffFixtures.Spec.standard()));
        importNative(HandoffFixtures.Spec.standard());
        var result = preparer().run();
        assertEquals("staged", result.get("outcome").asString(), result.toString());
        activate(result.get("graphVersionId").asString());
        var request = PublicationComposeRequest.parse(Canonical.bytes(result.get("request")));
        var recovered = GraphPublicationPreparer.operatorCompose(reader(), publications, composer(), request, decisionBytes(result));
        assertEquals("active_conflict", recovered.get("code").asString(), recovered.toString());
    }

    @Test void aSourceWithOnlyANewIssueIsStaged() {
        publish(importNative(HandoffFixtures.Spec.standard()));
        String incoming = importNative(HandoffFixtures.Spec.standard().withIssueId("issue:supply-2026q4"));
        var result = preparer().run();
        assertEquals("staged", result.get("outcome").asString(), result.toString());
        assertEquals(List.of(incoming), strings(result, "incomingVersionIds"));
        assertEquals(0, result.get("changes").size());
        assertEquals(Set.of(HandoffFixtures.ISSUE, "issue:supply-2026q4"), reader().read(result.get("graphVersionId").asString())
                .snapshot().issues().stream().map(i -> i.issueId()).collect(Collectors.toSet()));
    }

    @Test void sourcesThatDoNotOverlapBecomeOneCandidate() {
        publish(importNative(HandoffFixtures.Spec.standard()));
        var imported = List.of(importNative(HandoffFixtures.Spec.standard().withIssueId("issue:supply-2026q4")),
                importNative(HandoffFixtures.Spec.standard().withIssueId("issue:supply-2026q5")),
                importNative(HandoffFixtures.Spec.standard().withIssueId("issue:supply-2026q6")));
        var result = preparer().run();
        assertEquals("staged", result.get("outcome").asString(), result.toString());
        assertEquals(Set.copyOf(imported), Set.copyOf(strings(result, "incomingVersionIds")));
        assertEquals(4, reader().read(result.get("graphVersionId").asString()).snapshot().issues().size());
    }

    @Test void aBatchSplitByIssueAcrossHandoffsIsOneCandidate() {
        // The normal split (11-02 AI reply): every handoff holds whole issues, and one repeats the published issue unchanged.
        publish(importNative(HandoffFixtures.Spec.standard()));
        var imported = List.of(importNative(HandoffFixtures.Spec.standard().withIssueId("issue:supply-2026q4")),
                importNative(HandoffFixtures.Spec.standard().withIssueId("issue:supply-2026q5")),
                importNative(HandoffFixtures.Spec.standard()));
        var result = preparer().run();
        assertEquals("staged", result.get("outcome").asString(), result.toString());
        assertEquals(Set.copyOf(imported), Set.copyOf(strings(result, "incomingVersionIds")));
        assertEquals(0, result.get("changes").size());
        assertEquals(3, reader().read(result.get("graphVersionId").asString()).snapshot().issues().size());
    }

    @Test void preparesUnderAnAuthorityWithATextProjection() throws Exception {
        // #511: a collected source whose scope carries a text projection descriptor keeps the same grant decision.
        Files.writeString(authority, """
                {"schemaVersion":"zoop-ingestion-s2-1","revision":"registry-a","sources":[{
                  "sourceId":"synthetic-source","adapter":"collected-http","inputRoot":"/synthetic",
                  "allowedHosts":["example.invalid"],"scopes":[{"scopeId":"scope-a","selection":"all",
                    "initialCursor":null,"articleXPath":null,"timestampLimitations":["synthetic"],
                    "textProjection":{"profile":"korea-kogl1-caption-boundary-1","parent":{},
                      "excludedCaptionPaths":["/html/body/figure"],"rightsReceipt":{},"boundaryDecision":{}}}],
                  "grant":{"grantId":"operator-grant","revision":"rights-1","sourceId":"synthetic-source","enabled":true,
                    "rights":"known","allowedOperations":["read","store","quote-display"],"recipients":[],
                    "purposes":[],"evidence":["synthetic operator grant"],"expiresAt":null}}]}
                """);
        publish(importNative(HandoffFixtures.Spec.standard()));
        importNative(HandoffFixtures.Spec.standard().withIssueId("issue:supply-2026q4"));
        var result = preparer().run();
        assertEquals("staged", result.get("outcome").asString(), result.toString());
    }

    @Test void anOlderSourceAddedByAnOperatorDoesNotBringBackASourceLeftOut() {
        // A, B, C imported in that order; C is published alone, then an operator adds A. B stays out.
        String older = importNative(HandoffFixtures.Spec.standard());
        importNative(HandoffFixtures.Spec.standard().withEvent("2026-10-01", "day"));
        String published = publish(importNative(HandoffFixtures.Spec.standard()));
        activate(compose(published, older));
        var result = preparer().run();
        assertEquals("nothing_to_prepare", result.get("outcome").asString(), result.toString());
        String later = importNative(HandoffFixtures.Spec.standard());
        var next = preparer().run();
        assertEquals("staged", next.get("outcome").asString(), next.toString());
        assertEquals(List.of(later), strings(next, "incomingVersionIds"));
    }

    @Test void sourcesPastTheCapArePreparedAfterTheCappedCandidateIsPublished() {
        publish(importNative(HandoffFixtures.Spec.standard()));
        var imported = new java.util.ArrayList<String>();
        for (int index = 0; index < 21; index++) imported.add(importNative(HandoffFixtures.Spec.standard()));
        var first = preparer().run();
        assertEquals("staged", first.get("outcome").asString(), first.toString());
        assertEquals(imported.subList(0, 20), strings(first, "incomingVersionIds"));
        activate(first.get("graphVersionId").asString());
        var next = preparer().run();
        assertEquals("staged", next.get("outcome").asString(), next.toString());
        assertEquals(List.of(imported.getLast()), strings(next, "incomingVersionIds"));
    }

    @Test void anUnreadableSourceStopsPreparationAndIsNamed() throws Exception {
        publish(importNative(HandoffFixtures.Spec.standard()));
        String broken = importNative(HandoffFixtures.Spec.standard());
        String uri = jdbc.queryForObject("SELECT storage_uri FROM artifacts WHERE id = ?", String.class, "artifact-receipt-" + broken);
        Files.delete(temp.toRealPath().resolve("producer").resolve(uri.substring(uri.indexOf(':') + 1)));
        var result = preparer().run();
        assertEquals("failed", result.get("status").asString(), result.toString());
        assertEquals(broken, result.get("versionId").asString());
    }

    @Test void sourcesAdmittedTogetherThatDisagreeStopWithEverySide() {
        String published = publish(importNative(HandoffFixtures.Spec.standard()));
        importNative(HandoffFixtures.Spec.standard().withEvent("2026-10-01", "day"));
        importNative(HandoffFixtures.Spec.standard().withEvent("2026-10-02", "day"));
        var result = preparer().run();
        assertEquals("failed", result.get("status").asString());
        assertEquals("correction_required", result.get("code").asString(), result.toString());
        assertEquals(2, strings(result, "incomingVersionIds").size());
        assertEquals(List.of("base", "incoming", "incoming"),
                change(result, "eventTime").get("values").values().stream().map(v -> v.get("side").asString()).sorted().toList());
        assertEquals(published, versions.active().orElseThrow().id());
        assertEquals(0, (int) jdbc.queryForObject("SELECT count(*) FROM graph_publications WHERE base_version_id = ?", Integer.class, published));
    }

    // ---------------------------------------------------------------- round path (#55 PR-P3)

    @Test void theRoundPathPreparesOncePerNewImport() {
        publish(importNative(HandoffFixtures.Spec.standard()));
        String first = importNative(HandoffFixtures.Spec.standard());
        String round = roundImported(first, NOW.minusSeconds(10));
        var rounds = roundPreparer();
        rounds.afterPass(NOW);
        var rows = preparations();
        assertEquals(1, rows.size());
        assertEquals("staged", rows.getFirst().get("code"));
        assertEquals(round, rows.getFirst().get("round_id"));
        assertNotNull(rows.getFirst().get("request"), "the fixed inputs are kept");
        rounds.afterPass(NOW.plusSeconds(15));
        assertEquals(1, preparations().size(), "no new import, no new attempt");

        String second = importNative(HandoffFixtures.Spec.standard());
        roundImported(second, NOW.plusSeconds(20));
        rounds.afterPass(NOW.plusSeconds(30));
        rows = preparations();
        assertEquals(2, rows.size());
        assertEquals("staged", rows.get(1).get("code"));
        assertNotEquals(rows.getFirst().get("graph_version_id"), rows.get(1).get("graph_version_id"));
    }

    @Test void aChangedValueIsRecordedOnceWithItsInputs() {
        publish(importNative(HandoffFixtures.Spec.standard()));
        roundImported(importNative(HandoffFixtures.Spec.standard().withEvent("2026-10-01", "day")), NOW.minusSeconds(10));
        var rounds = roundPreparer();
        rounds.afterPass(NOW);
        rounds.afterPass(NOW.plusSeconds(15));
        var rows = preparations();
        assertEquals(1, rows.size());
        assertEquals("failed", rows.getFirst().get("status"));
        assertEquals("correction_required", rows.getFirst().get("code"));
        assertNotNull(rows.getFirst().get("request"));
        assertNotNull(rows.getFirst().get("decisions"));
    }

    @Test void anAttemptThatStoppedAfterCommittingIsRecoveredAsUnchanged() {
        publish(importNative(HandoffFixtures.Spec.standard()));
        String round = roundImported(importNative(HandoffFixtures.Spec.standard()), NOW.minusSeconds(10));
        // The process stopped after the composition committed, before its result was written.
        var result = preparer().run((active, request, decisions) -> journal().begin(round, publications.newestImport().orElseThrow(), null, active, request, decisions, NOW));
        assertEquals("staged", result.get("outcome").asString(), result.toString());
        roundPreparer().afterPass(NOW.plusSeconds(15));
        var rows = preparations();
        assertEquals(2, rows.size(), "the recovery, and no new preparation for the same import");
        assertNull(rows.getFirst().get("status"), "the stopped attempt keeps no result");
        assertEquals(rows.getFirst().get("id"), rows.get(1).get("recovery_of"));
        assertEquals("unchanged", rows.get(1).get("code"));
        assertEquals(result.get("graphVersionId").asString(), rows.get(1).get("graph_version_id"));
        assertArrayEquals((byte[]) rows.getFirst().get("request"), (byte[]) rows.get(1).get("request"));
    }

    @Test void anAttemptThatStoppedBeforeComposingIsComposedFromItsFixedInputs() {
        publish(importNative(HandoffFixtures.Spec.standard()));
        String round = roundImported(importNative(HandoffFixtures.Spec.standard()), NOW.minusSeconds(10));
        var result = preparer().run((active, request, decisions) -> {
            journal().begin(round, publications.newestImport().orElseThrow(), null, active, request, decisions, NOW);
            throw new IllegalStateException("stopped");
        });
        assertEquals("internal_error", result.get("code").asString());
        assertEquals(1, (int) jdbc.queryForObject("SELECT count(*) FROM graph_publications", Integer.class), "only the published one; nothing composed yet");
        roundPreparer().afterPass(NOW.plusSeconds(15));
        var rows = preparations();
        assertEquals(2, rows.size());
        assertEquals("staged", rows.get(1).get("code"));
    }

    @Test void aRecoveryThatFailsUnexpectedlyIsRecoveredAgainBeforeANewImportIsPrepared() {
        publish(importNative(HandoffFixtures.Spec.standard()));
        String round = roundImported(importNative(HandoffFixtures.Spec.standard()), NOW.minusSeconds(10));
        // The composition committed, but the process stopped before its result was written.
        var result = preparer().run((active, request, decisions) -> journal().begin(round, publications.newestImport().orElseThrow(), null, active, request, decisions, NOW));
        String candidate = result.get("graphVersionId").asString();
        // The recovery's first read fails unexpectedly; the cause is gone by the next try.
        var reader = org.mockito.Mockito.spy(reader());
        org.mockito.Mockito.doThrow(new IllegalStateException("transient")).doCallRealMethod().when(reader).read(org.mockito.ArgumentMatchers.anyString());
        var clock = new MovingClock(NOW.plusSeconds(15));
        var rounds = roundPreparer(reader, clock);
        rounds.afterPass(clock.instant());
        var rows = preparations();
        assertEquals(2, rows.size());
        assertEquals(rows.getFirst().get("id"), rows.get(1).get("recovery_of"));
        assertEquals("internal_error", rows.get(1).get("code"));
        // A new import arrives while the original is undecided: no new preparation before the original is settled.
        roundImported(importNative(HandoffFixtures.Spec.standard()), NOW.plusSeconds(20));
        clock.set(NOW.plusSeconds(60));
        rounds.afterPass(clock.instant());
        assertEquals(2, preparations().size(), "the recovery waits; the new import does not start a preparation");
        // After the wait the same fixed inputs are recovered and settle as the committed candidate; then the new import is prepared.
        clock.set(NOW.plusSeconds(15 + 301));
        rounds.afterPass(clock.instant());
        rows = preparations();
        assertEquals(4, rows.size(), rows.toString());
        assertEquals(rows.getFirst().get("id"), rows.get(2).get("recovery_of"));
        assertEquals("unchanged", rows.get(2).get("code"));
        assertEquals(candidate, rows.get(2).get("graph_version_id"));
        assertNull(rows.get(3).get("recovery_of"));
        assertTrue(Set.of("staged", "nothing_to_prepare").contains((String) rows.get(3).get("code")), rows.get(3).toString());
    }

    /** A clock the round-path tests move past the recovery wait. */
    private static final class MovingClock extends Clock {
        private volatile Instant now;
        MovingClock(Instant now) { this.now = now; }
        void set(Instant at) { now = at; }
        @Override public ZoneOffset getZone() { return ZoneOffset.UTC; }
        @Override public Clock withZone(java.time.ZoneId zone) { return this; }
        @Override public Instant instant() { return now; }
    }

    @Test void aRecoveryAfterTheActiveVersionMovedIsAConflictThenANewPreparation() {
        publish(importNative(HandoffFixtures.Spec.standard()));
        String round = roundImported(importNative(HandoffFixtures.Spec.standard()), NOW.minusSeconds(10));
        var result = preparer().run((active, request, decisions) -> journal().begin(round, publications.newestImport().orElseThrow(), null, active, request, decisions, NOW));
        activate(result.get("graphVersionId").asString());
        roundPreparer().afterPass(NOW.plusSeconds(15));
        var rows = preparations();
        assertEquals(List.of("active_conflict", "nothing_to_prepare"), List.of(rows.get(1).get("code"), rows.get(2).get("code")));
        assertNull(rows.get(2).get("recovery_of"));
    }

    @Test void aBusyImportLockWaitsForTheNextPass() {
        publish(importNative(HandoffFixtures.Spec.standard()));
        roundImported(importNative(HandoffFixtures.Spec.standard()), NOW.minusSeconds(10));
        try (var held = new JdbcGraphRoundImportLock(dataSource).tryAcquire().orElseThrow()) {
            roundPreparer().afterPass(NOW);
            assertEquals(0, preparations().size());
        }
        roundPreparer().afterPass(NOW.plusSeconds(15));
        assertEquals(1, preparations().size());
    }

    @Test void thePreparationJournalKeepsItsBytesAndWritesAResultOnce() {
        publish(importNative(HandoffFixtures.Spec.standard()));
        roundImported(importNative(HandoffFixtures.Spec.standard()), NOW.minusSeconds(10));
        roundPreparer().afterPass(NOW);
        long id = ((Number) preparations().getFirst().get("id")).longValue();
        assertThrows(Exception.class, () -> jdbc.update("UPDATE graph_publication_preparations SET request = ? WHERE id = ?", new byte[] {1}, id));
        assertThrows(Exception.class, () -> jdbc.update("UPDATE graph_publication_preparations SET code = 'other' WHERE id = ?", id));
        assertThrows(Exception.class, () -> jdbc.update("DELETE FROM graph_publication_preparations WHERE id = ?", id));
    }

    private JdbcGraphPublicationPreparationRepository journal() {
        return new JdbcGraphPublicationPreparationRepository(named);
    }

    private GraphRoundPreparer roundPreparer() {
        return roundPreparer(reader(), CLOCK);
    }
    private GraphRoundPreparer roundPreparer(GraphPublicationReader reader, Clock clock) {
        var composer = composer();
        return new GraphRoundPreparer(new JdbcGraphRoundRepository(named, tools.jackson.databind.json.JsonMapper.builder().build(),
                new DataSourceTransactionManager(dataSource)), journal(), new JdbcGraphRoundImportLock(dataSource),
                new GraphPublicationPreparer(versions, graph, publications, reader, composer), reader, publications, composer,
                Duration.ofMinutes(5), 3, clock);
    }

    /** A round whose import of {@code versionId} committed at {@code committedAt}; returns its id. */
    private String roundImported(String versionId, Instant committedAt) {
        Instant slotAt = Instant.parse("2026-11-02T00:05:00Z").plus(Duration.ofMinutes(30L * slots++));
        String id = "round-" + DateTimeFormatter.ofPattern("yyyyMMdd'T'HHmm").withZone(ZoneId.of("Asia/Seoul")).format(slotAt);
        jdbc.update("""
                INSERT INTO graph_rounds (round_id, slot_at, stage, graph_version_id, version_committed_at, started_by, created_at, updated_at)
                VALUES (?, ?, 'imported', ?, ?, 'system:scheduler', ?, ?)
                """, id, Timestamp.from(slotAt), versionId, Timestamp.from(committedAt), Timestamp.from(committedAt), Timestamp.from(committedAt));
        return id;
    }

    private List<java.util.Map<String, Object>> preparations() {
        return jdbc.queryForList("""
                SELECT id, round_id, recovery_of, request, decisions, status, code, graph_version_id
                FROM graph_publication_preparations ORDER BY id
                """);
    }

    private GraphPublicationReader reader() {
        return new GraphPublicationReader(graph, registry, files, publications);
    }

    private GraphPublicationComposer composer() {
        var sources = new DocumentReadSources(authority);
        var rights = new GraphPublicationAuthority(registry, sources,
                version -> new DisclosureExclusions(0, Set.of(), Set.of(), Set.of(), Set.of()), CLOCK);
        return new GraphPublicationComposer(files, graph, registry, versions, publications, reader(), rights, sources, transaction, CLOCK);
    }

    private GraphPublicationPreparer preparer() {
        return new GraphPublicationPreparer(versions, graph, publications, reader(), composer());
    }

    private static byte[] decisionBytes(ObjectNode result) {
        return Base64.getDecoder().decode(result.get("decisionsBase64").asString());
    }

    private static tools.jackson.databind.JsonNode change(ObjectNode result, String field) {
        return result.get("changes").values().stream().filter(c -> field.equals(c.get("field").asString())).findFirst().orElseThrow();
    }

    private String importNative(HandoffFixtures.Spec spec) {
        var built = HandoffFixtures.build(spec.withHandoffId("prepare-" + UUID.randomUUID()));
        var importer = new GraphHandoffImporter(new HandoffFixtures.FakeHandoff(built.envelopeBytes()), new HandoffFixtures.FakeIngestion(),
                new IngestionExportParser(), files, registry, graph, transaction, CLOCK);
        assertTrue(importer.run(built.request()).succeeded());
        return built.versionId();
    }

    /** Composes the first publication from {@code source} like the operator B4 and makes it the active version a person approved. */
    private String publish(String source) {
        String id = compose(null, source);
        jdbc.update("UPDATE graph_versions SET active = true WHERE id = ?", id);
        jdbc.update("""
                INSERT INTO graph_activations (version_id, previous_version_id, action, actor_kind, pointer_changed, admin_id,
                    admin_email_snapshot, reason, activated_at) VALUES (?, NULL, 'activate', 'system', true, NULL, 'system', 'synthetic', ?)
                """, id, Timestamp.from(NOW.minusSeconds(60)));
        return id;
    }

    /** An operator compose (B4) of {@code source} on {@code base} with no decisions; not activated. */
    private String compose(String base, String source) {
        byte[] decisions = Canonical.bytes(PublicationMerger.emptyDecisions().node());
        var state = graph.publicationState();
        var pins = new java.util.TreeMap<String, String>();
        pins.put(source, registry.findArtifact("artifact-receipt-" + source).orElseThrow().sha256());
        String basePin = base == null ? null : registry.findArtifact("artifact-receipt-" + base).orElseThrow().sha256();
        var request = new PublicationComposeRequest(base, List.of(source), base, basePin, pins, state.ruleRevision(), state.reviewRevision(),
                Canonical.sha256(decisions), "synthetic");
        var composed = composer().run(request, decisions);
        assertEquals("succeeded", composed.get("status").asString(), composed.toString());
        return composed.get("graphVersionId").asString();
    }

    private void activate(String id) {
        String previous = versions.active().orElseThrow().id();
        jdbc.update("UPDATE graph_versions SET active = false WHERE active");
        jdbc.update("UPDATE graph_versions SET active = true WHERE id = ?", id);
        jdbc.update("""
                INSERT INTO graph_activations (version_id, previous_version_id, action, actor_kind, pointer_changed, admin_id,
                    admin_email_snapshot, reason, activated_at) VALUES (?, ?, 'activate', 'system', true, NULL, 'system', 'synthetic', ?)
                """, id, previous, Timestamp.from(NOW));
    }

    private static List<String> strings(ObjectNode node, String field) {
        return node.get(field).values().stream().map(v -> v.asString()).toList();
    }
}
