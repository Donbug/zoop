package com.zoop.document.bindings;

import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.List;
import java.util.Map;

import com.zoop.ZoopApplication;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import com.zoop.common.json.StrictJson.Obj;
import com.zoop.document.bindings.BindingSelection.VersionKey;
import com.zoop.document.bindings.DocumentBindingsExporter.Export;
import com.zoop.document.repository.ArtifactRow;
import com.zoop.document.repository.DocumentRegistryRepository;
import com.zoop.document.repository.VersionRow;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.springframework.boot.WebApplicationType;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

/**
 * The bindings export against the disposable company test database: the real registry tables and SQL, rows registered the way
 * the document import registers them. The bytes must be what the graph import later verifies a bundle against (the text
 * artifact's SHA-256) and what the AI freeze reads.
 */
@Tag("graph-postgres")
class DocumentBindingsPostgresIntegrationTest {
    private static final String ARTICLE_A = "doc-" + "a".repeat(64);
    private static final String ARTICLE_B = "doc-" + "b".repeat(64);
    private static final String VERSION_1 = "1".repeat(64);
    private static final String VERSION_2 = "2".repeat(64);
    private static final String VERSION_3 = "3".repeat(64);
    private static final Instant AT = Instant.parse("2026-10-14T01:00:00Z");

    private static ConfigurableApplicationContext context;
    private static JdbcTemplate jdbc;
    private static DocumentRegistryRepository registry;
    private static TransactionTemplate transaction;
    private static DocumentBindingsExporter exporter;

    @BeforeAll
    static void start() {
        String url = System.getenv("ZOOP_COMPANY_TEST_DB_URL");
        if (url == null || !url.matches("jdbc:postgresql://127\\.0\\.0\\.1:[0-9]+/zoop_company_test_19")) {
            throw new IllegalStateException("Set ZOOP_COMPANY_TEST_DB_URL to the dedicated localhost zoop_company_test_19 database");
        }
        String password = System.getenv().getOrDefault("ZOOP_COMPANY_TEST_DB_PASSWORD", "");
        context = new SpringApplicationBuilder(ZoopApplication.class)
                .web(WebApplicationType.NONE)
                .run("--spring.datasource.url=" + url,
                        "--spring.datasource.username=company_test", "--spring.datasource.password=" + password,
                        "--spring.jpa.hibernate.ddl-auto=validate", "--zoop.ai.client.enabled=false",
                        "--ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test",
                        "--ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA");
        jdbc = context.getBean(JdbcTemplate.class);
        registry = context.getBean(DocumentRegistryRepository.class);
        transaction = new TransactionTemplate(context.getBean(PlatformTransactionManager.class));
        exporter = new DocumentBindingsExporter(new JdbcDocumentBindingsRepository(context.getBean(NamedParameterJdbcTemplate.class)));
    }

    @AfterAll
    static void stop() {
        if (jdbc != null) clean();
        if (context != null) context.close();
    }

    private static void clean() {
        jdbc.update("DELETE FROM evidence WHERE article_id IN (?, ?)", ARTICLE_A, ARTICLE_B);
        jdbc.update("DELETE FROM article_versions WHERE article_id IN (?, ?)", ARTICLE_A, ARTICLE_B);
        jdbc.update("DELETE FROM articles WHERE id IN (?, ?)", ARTICLE_A, ARTICLE_B);
        jdbc.update("DELETE FROM artifacts WHERE id IN (?, ?, ?)", "text-" + VERSION_1, "text-" + VERSION_2, "text-" + VERSION_3);
    }

    @BeforeEach
    void setUp() {
        clean();
        transaction.executeWithoutResult(status -> {
            registry.insertArticleIfAbsent(ARTICLE_A, "news", "synthetic-source", AT);
            registry.insertArticleIfAbsent(ARTICLE_B, "disclosure", "synthetic-source", AT);
            version(ARTICLE_A, VERSION_1, "첫 본문");
            version(ARTICLE_A, VERSION_2, "둘째 본문");
            version(ARTICLE_B, VERSION_3, "공시 본문");
        });
    }

    @AfterEach
    void tearDown() {
        clean();
    }

    /** What the document import registers for one version: the text artifact (hash of the UTF-8 bytes) and the version row. */
    private static void version(String articleId, String version, String text) {
        byte[] utf8 = text.getBytes(StandardCharsets.UTF_8);
        String artifactId = "text-" + version;
        registry.insertArtifactIfAbsent(new ArtifactRow(artifactId, "extracted_text", "file:///test/" + artifactId + ".txt",
                Canonical.sha256(utf8), utf8.length, "text/plain; charset=utf-8", AT));
        registry.insertVersionIfAbsent(new VersionRow(articleId, version, "제목 " + version.charAt(0), null,
                "https://example.invalid/" + version.charAt(0), AT, null, "datetime", null, artifactId, AT));
    }

    private static String sha(String text) {
        return Canonical.sha256(text.getBytes(StandardCharsets.UTF_8));
    }

    @Test
    void bindsEveryRegisteredVersionWithTheStoredTextHashInArticleAndVersionOrder() {
        Export export = exporter.export(DocumentBindingsScope.AVAILABLE, null);

        Obj root = StrictJson.parseObject(export.bytes());
        List<Obj> bindings = root.objects("bindings");
        assertEquals(3, bindings.size());
        assertEquals(List.of(ARTICLE_A, ARTICLE_A, ARTICLE_B), bindings.stream().map(b -> b.string("articleId")).toList());
        assertEquals(List.of(VERSION_1, VERSION_2, VERSION_3), bindings.stream().map(b -> b.string("articleVersion")).toList());
        assertEquals(List.of(sha("첫 본문"), sha("둘째 본문"), sha("공시 본문")),
                bindings.stream().map(b -> b.string("textSha256")).toList());
        assertEquals(Canonical.sha256(export.bytes()), export.sha256());
        assertEquals(Map.of(), export.excluded());
    }

    @Test
    void aWithdrawnArticleIsLeftOutOfTheAvailableScopeAndCountedButBoundByAll() {
        jdbc.update("UPDATE articles SET access_status = 'private' WHERE id = ?", ARTICLE_B);

        Export available = exporter.export(DocumentBindingsScope.AVAILABLE, null);
        Export all = exporter.export(DocumentBindingsScope.ALL, null);

        assertEquals(2, available.count());
        assertEquals(Map.of("private", 1), available.excluded());
        assertEquals(3, all.count());
    }

    @Test
    void aSelectionIsServedFromTheSameRowsAndAMissingVersionIsRefused() {
        Export export = exporter.export(DocumentBindingsScope.AVAILABLE,
                new BindingSelection(List.of(new VersionKey(ARTICLE_B, VERSION_3))));
        assertEquals(1, export.count());
        assertEquals(ARTICLE_B, StrictJson.parseObject(export.bytes()).objects("bindings").get(0).string("documentId"));

        DocumentBindingsException refused = assertThrows(DocumentBindingsException.class, () -> exporter.export(
                DocumentBindingsScope.AVAILABLE, new BindingSelection(List.of(new VersionKey(ARTICLE_B, VERSION_1)))));
        assertEquals(DocumentBindingsFailure.SELECTION_UNREGISTERED, refused.failure());
    }
}
