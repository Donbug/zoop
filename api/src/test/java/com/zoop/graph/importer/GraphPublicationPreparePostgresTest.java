package com.zoop.graph.importer;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.UUID;
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
import com.zoop.graph.publication.GraphPublicationReader;
import com.zoop.graph.publication.JdbcGraphPublicationRepository;
import com.zoop.graph.publication.PublicationComposeRequest;
import com.zoop.graph.publication.PublicationMerger;
import com.zoop.graph.read.DisclosureExclusions;
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
    private ArtifactFileStore files;
    private Path authority;

    @BeforeEach void start() throws Exception {
        schema = "prepare_" + UUID.randomUUID().toString().replace("-", "");
        String url = System.getenv("ZOOP_COMPANY_TEST_DB_URL");
        if (url == null || !url.matches("jdbc:postgresql://127\\.0\\.0\\.1:[0-9]+/zoop_company_test_19")) {
            throw new IllegalStateException("Set ZOOP_COMPANY_TEST_DB_URL to the dedicated localhost zoop_company_test_19 database");
        }
        var dataSource = new DriverManagerDataSource(url + "?currentSchema=" + schema + ",public", "company_test",
                System.getenv().getOrDefault("ZOOP_COMPANY_TEST_DB_PASSWORD", ""));
        jdbc = new JdbcTemplate(dataSource);
        jdbc.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public");
        jdbc.execute("CREATE EXTENSION IF NOT EXISTS btree_gist WITH SCHEMA public");
        Flyway.configure().dataSource(dataSource).schemas(schema).defaultSchema(schema).load().migrate();
        var named = new NamedParameterJdbcTemplate(jdbc);
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

    @Test void stagesTheNewestNativeValueAsAnInactiveCandidateAndRerunIsUnchanged() {
        String published = publish(importNative(HandoffFixtures.Spec.standard()));
        String incoming = importNative(HandoffFixtures.Spec.standard().withEvent("2026-10-01", "day"));

        var result = preparer().run();
        assertEquals("succeeded", result.get("status").asString(), result.toString());
        assertEquals("staged", result.get("outcome").asString());
        assertEquals(List.of(incoming), strings(result, "incomingVersionIds"));
        String candidate = result.get("graphVersionId").asString();
        var reader = reader();
        var publication = reader.read(candidate);
        assertEquals(published, publication.baseVersionId());
        assertEquals(published, versions.active().orElseThrow().id());
        assertFalse(versions.everActivated(candidate));
        assertTrue(publication.snapshot().issues().stream().allMatch(i -> "2026-10-01".equals(i.eventTime())), publication.snapshot().issues().toString());
        assertTrue(result.get("autoResolutions").values().stream().anyMatch(r -> "eventTime".equals(r.get("field").asString())));
        assertTrue(PublicationMerger.claimsAutomaticReviewer(publication.effectiveDecisions()));
        // The kept request is a valid operator compose request for the same decisions.
        var request = PublicationComposeRequest.parse(Canonical.bytes(result.get("request")));
        assertEquals(Canonical.sha256(Canonical.bytes(result.get("decisions"))), request.decisionsSha256());

        var again = preparer().run();
        assertEquals("unchanged", again.get("outcome").asString(), again.toString());
        assertEquals(candidate, again.get("graphVersionId").asString());
    }

    @Test void nothingToPrepareWithoutNewImportsOrForSourcesImportedBeforeTheLastActivation() {
        publish(importNative(HandoffFixtures.Spec.standard()));
        assertEquals("nothing_to_prepare", preparer().run().get("outcome").asString());

        // A source imported before a person's last activation was left out on purpose and is not added back.
        importNative(HandoffFixtures.Spec.standard().withEvent("2026-10-01", "day"));
        jdbc.update("UPDATE graph_activations SET activated_at = ?", Timestamp.from(NOW.plusSeconds(60)));
        var result = preparer().run();
        assertEquals("nothing_to_prepare", result.get("outcome").asString(), result.toString());
    }

    @Test void sourcesAdmittedTogetherThatDisagreeStopForAPersonAndKeepTheRequest() {
        String published = publish(importNative(HandoffFixtures.Spec.standard()));
        importNative(HandoffFixtures.Spec.standard().withEvent("2026-10-01", "day"));
        importNative(HandoffFixtures.Spec.standard().withEvent("2026-10-02", "day"));
        var result = preparer().run();
        assertEquals("failed", result.get("status").asString());
        assertEquals("correction_required", result.get("code").asString(), result.toString());
        assertEquals(2, strings(result, "incomingVersionIds").size());
        assertNotNull(PublicationComposeRequest.parse(Canonical.bytes(result.get("request"))));
        assertEquals(published, versions.active().orElseThrow().id());
        assertEquals(0, (int) jdbc.queryForObject("SELECT count(*) FROM graph_publications WHERE base_version_id = ?", Integer.class, published));
    }

    private GraphPublicationReader reader() {
        return new GraphPublicationReader(graph, registry, files, publications);
    }

    private GraphPublicationPreparer preparer() {
        var sources = new DocumentReadSources(authority);
        var reader = reader();
        var rights = new GraphPublicationAuthority(registry, sources,
                version -> new DisclosureExclusions(0, java.util.Set.of(), java.util.Set.of(), java.util.Set.of(), java.util.Set.of()), CLOCK);
        var composer = new GraphPublicationComposer(files, graph, registry, versions, publications, reader, rights, sources, transaction, CLOCK);
        return new GraphPublicationPreparer(versions, graph, publications, reader, composer, "prepare");
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
        var sources = new DocumentReadSources(authority);
        var reader = reader();
        var rights = new GraphPublicationAuthority(registry, sources,
                version -> new DisclosureExclusions(0, java.util.Set.of(), java.util.Set.of(), java.util.Set.of(), java.util.Set.of()), CLOCK);
        byte[] decisions = Canonical.bytes(PublicationMerger.emptyDecisions().node());
        var state = graph.publicationState();
        var pins = new java.util.TreeMap<String, String>();
        pins.put(source, registry.findArtifact("artifact-receipt-" + source).orElseThrow().sha256());
        var request = new PublicationComposeRequest(null, List.of(source), null, null, pins, state.ruleRevision(), state.reviewRevision(),
                Canonical.sha256(decisions), "synthetic");
        var composed = new GraphPublicationComposer(files, graph, registry, versions, publications, reader, rights, sources, transaction, CLOCK)
                .run(request, decisions);
        assertEquals("succeeded", composed.get("status").asString(), composed.toString());
        String id = composed.get("graphVersionId").asString();
        jdbc.update("UPDATE graph_versions SET active = true WHERE id = ?", id);
        jdbc.update("""
                INSERT INTO graph_activations (version_id, previous_version_id, action, actor_kind, pointer_changed, admin_id,
                    admin_email_snapshot, reason, activated_at) VALUES (?, NULL, 'activate', 'system', true, NULL, 'system', 'synthetic', ?)
                """, id, Timestamp.from(NOW.minusSeconds(60)));
        return id;
    }

    private static List<String> strings(ObjectNode node, String field) {
        return node.get(field).values().stream().map(v -> v.asString()).toList();
    }
}
