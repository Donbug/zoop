package com.zoop.graph.publication;

import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.json.StrictJson;
import com.zoop.document.evidence.service.DocumentReadSources;
import com.zoop.document.repository.ArtifactRow;
import com.zoop.document.repository.DocumentRegistryRepository.ArticleVersion;
import com.zoop.document.repository.JdbcDocumentRegistryRepository;
import com.zoop.document.repository.VersionRow;
import com.zoop.graph.publication.GraphPublicationReader.Publication;
import com.zoop.graph.read.DisclosureExclusions;
import com.zoop.graph.read.GraphSnapshotFilter;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowCallbackHandler;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.jdbc.core.namedparam.SqlParameterSource;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.transaction.support.TransactionTemplate;
import static org.junit.jupiter.api.Assertions.*;

@Tag("graph-postgres")
class GraphPublicationAuthorityPostgresTest {
    private static final Instant NOW = Instant.parse("2026-10-31T01:00:00Z");
    private static final String SCHEMA = "authority_" + UUID.randomUUID().toString().replace("-", "");
    private static DriverManagerDataSource dataSource;
    private static JdbcTemplate jdbc;
    @TempDir Path temp;
    private CountingJdbc named;
    private JdbcDocumentRegistryRepository registry;
    private TransactionTemplate read;
    private GraphPublicationAuthority authority;
    private Publication publication;
    private Path second;
    private final Map<String, DisclosureExclusions> exclusions = new HashMap<>();

    @BeforeAll static void start() {
        String url = System.getenv("ZOOP_COMPANY_TEST_DB_URL");
        if (url == null || !url.matches("jdbc:postgresql://127\\.0\\.0\\.1:[0-9]+/zoop_company_test_19"))
            throw new IllegalStateException("Set ZOOP_COMPANY_TEST_DB_URL to the dedicated localhost zoop_company_test_19 database");
        dataSource = new DriverManagerDataSource(url + "?currentSchema=" + SCHEMA + ",public", "company_test",
                System.getenv().getOrDefault("ZOOP_COMPANY_TEST_DB_PASSWORD", ""));
        jdbc = new JdbcTemplate(dataSource);
        jdbc.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public");
        jdbc.execute("CREATE EXTENSION IF NOT EXISTS btree_gist WITH SCHEMA public");
        Flyway.configure().dataSource(dataSource).schemas(SCHEMA).defaultSchema(SCHEMA).load().migrate();
    }

    @AfterAll static void stop() {
        if (jdbc != null) jdbc.execute("DROP SCHEMA IF EXISTS " + SCHEMA + " CASCADE");
    }

    @BeforeEach void setup() throws Exception {
        jdbc.execute("TRUNCATE articles, artifacts CASCADE");
        named = new CountingJdbc();
        registry = new JdbcDocumentRegistryRepository(named);
        read = new TransactionTemplate(new DataSourceTransactionManager(dataSource));
        read.setReadOnly(true); read.setIsolationLevel(Connection.TRANSACTION_REPEATABLE_READ); read.setTimeout(5);
        Path first = temp.resolve("first.json"); second = temp.resolve("second.json");
        Files.writeString(first, GraphPublicationAuthorityTest.registry("grant-a", true));
        Files.writeString(second, GraphPublicationAuthorityTest.registry("grant-b", true));
        var routes = StrictJson.newObject(); routes.put("schemaVersion", "zoop-source-authority-set-1");
        var authorities = routes.putArray("authorities");
        authorities.addObject().put("sourceId", "source").put("grantId", "grant-a").put("revision", "r1").put("sources", first.toRealPath().toString());
        authorities.addObject().put("sourceId", "source").put("grantId", "grant-b").put("revision", "r1").put("sources", second.toRealPath().toString());
        Path wrapper = temp.resolve("authority.json"); Files.write(wrapper, StrictJson.write(routes));
        var a = PublicationMergerTest.source(0, "issue-0", "A");
        var b = PublicationMergerTest.source(1, "issue-1", "B");
        var p = a.projection();
        var q = new PublicGraphSnapshot(p.snapshotFormat(), b.sourceVersionId(), b.sourceId(), p.companies(), p.issues(), p.relations(), p.articles(), p.evidence());
        publication = GraphPublicationAuthorityTest.publication("published", List.of(
                GraphPublicationAuthorityTest.withBundle(a, p, "grant-a"), GraphPublicationAuthorityTest.withBundle(b, q, "grant-b")));
        var article = p.articles().getFirst();
        registry.insertArticleIfAbsent(article.articleId(), "news", "source", NOW);
        registry.insertArtifactIfAbsent(new ArtifactRow("text", "extracted_text", "artifact-root:extracted_text/text.txt", "f".repeat(64), 1, "text/plain", NOW));
        registry.insertVersionIfAbsent(new VersionRow(article.articleId(), article.version(), article.title(), "Publisher", article.url(), null,
                LocalDate.parse("2026-10-01"), "day", null, "text", NOW));
        authority = new GraphPublicationAuthority(registry, new DocumentReadSources(wrapper.toRealPath()),
                version -> exclusions.getOrDefault(version, DisclosureExclusions.NONE), Clock.fixed(NOW, ZoneOffset.UTC));
    }

    @Test void sharedFactsKeepEachContributionsLiveRightsAndExclusions() throws Exception {
        read.executeWithoutResult(status -> {
            for (var source : publication.contributions()) for (var article : source.projection().articles()) {
                assertEquals("source", registry.findArticle(article.articleId()).orElseThrow().provider());
                var version = registry.findVersion(article.articleId(), article.version()).orElseThrow();
                assertEquals("f".repeat(64), registry.findArtifact(version.textArtifactId()).orElseThrow().sha256());
            }
        });
        assertEquals(6, named.queries);
        named.queries = 0;
        assertEquals(publication.snapshot(), GraphSnapshotFilter.apply(publication.snapshot(), null, overlay()));
        assertEquals(1, named.queries);
        read.executeWithoutResult(status -> authority.requireFullRights(publication, "test"));
        assertEquals(2, named.queries);
        String source = publication.contributions().getLast().sourceVersionId();
        exclusions.put(source, new DisclosureExclusions(7, Set.of("issue-0"), Set.of(), Set.of()));
        assertEquals(Set.of("issue-0"), overlay().issueIds());
        exclusions.clear();
        String permitting = GraphPublicationAuthorityTest.registry("grant-b", true);
        for (String denied : List.of(permitting.replace("\"enabled\":true", "\"enabled\":false"),
                permitting.replace("\"expiresAt\":null", "\"expiresAt\":\"" + NOW + "\""),
                permitting.replace("\"revision\":\"r1\"", "\"revision\":\"r2\""),
                permitting.replace("\"read\",", ""), permitting.replace("\"store\",", ""),
                permitting.replace(",\"quote-display\"", ""))) {
            Files.writeString(second, denied);
            int before = named.queries;
            var excluded = overlay();
            assertEquals(Set.of("issue-0"), excluded.issueIds());
            assertEquals(0, GraphSnapshotFilter.apply(publication.snapshot(), null, excluded).issues().size());
            assertEquals(before + 1, named.queries);
            assertEquals("rights_denied", assertThrows(PublicationException.class,
                    () -> read.executeWithoutResult(status -> authority.requireFullRights(publication, "test"))).code());
        }
        Files.writeString(second, permitting);
        assertEquals(Set.of(), overlay().articleTargets());
        jdbc.update("UPDATE articles SET access_status = 'private'");
        assertEquals(Set.of("issue-0"), overlay().issueIds());
        System.out.println("AUTHORITY_QUERY_PROOF sharedContributions=2 uniqueArticleVersions=1 oldRegistryQueries=6 registryQueriesPerRead=1 rightsVariants=6");
    }

    @Test void missingVersionsAndHashMismatchesMakeTheWholeReadUnavailable() {
        var original = publication;
        var second = publication.contributions().getLast();
        var bundle = (tools.jackson.databind.node.ObjectNode) second.bundle().node().deepCopy();
        ((tools.jackson.databind.node.ObjectNode) bundle.get("articles").get(0)).put("textSha256", "e".repeat(64));
        var changed = new GraphPublicationReader.Contribution(second.sourceVersionId(), second.sourceId(), second.sourceKind(),
                second.receipt(), second.projectionArtifact(), second.projection(), StrictJson.Obj.of(bundle));
        publication = GraphPublicationAuthorityTest.publication("mismatched", List.of(publication.contributions().getFirst(), changed));
        unavailable("basis_mismatch");
        publication = original;
        var article = publication.snapshot().articles().getFirst();
        jdbc.update("DELETE FROM article_versions");
        registry.insertVersionIfAbsent(new VersionRow(article.articleId(), "b".repeat(64), article.title(), "Publisher", article.url(), null,
                LocalDate.parse("2026-10-01"), "day", null, "text", NOW));
        unavailable("basis_unavailable");
        jdbc.update("DELETE FROM article_versions");
        jdbc.update("DELETE FROM articles");
        unavailable("basis_unavailable");
    }

    @Test void exactVersionsUseBoundedJoinsAndOneRepeatableReadSnapshot() {
        String article = publication.snapshot().articles().getFirst().articleId();
        Set<ArticleVersion> identities = new HashSet<>();
        for (int index = 0; index < 257; index++) {
            String version = "%064x".formatted(index);
            registry.insertVersionIfAbsent(new VersionRow(article, version, "version-" + index, null, null, null,
                    null, "unknown", null, "text", NOW));
            identities.add(new ArticleVersion(article, version));
        }
        identities.add(new ArticleVersion(article, "missing"));
        var writer = new JdbcTemplate(new DriverManagerDataSource(dataSource.getUrl(), dataSource.getUsername(), dataSource.getPassword()));
        named.afterFirst = () -> writer.update("UPDATE articles SET access_status = 'private'");
        var found = read.execute(status -> {
            assertEquals("repeatable read", jdbc.queryForObject("SHOW transaction_isolation", String.class));
            assertEquals("on", jdbc.queryForObject("SHOW transaction_read_only", String.class));
            return registry.findArticleFacts(identities);
        });
        assertEquals(2, named.queries);
        assertEquals(257, found.size());
        for (int index = 0; index < 257; index++) {
            var facts = found.get(new ArticleVersion(article, "%064x".formatted(index)));
            assertEquals("version-" + index, facts.version().title());
            assertEquals("available", facts.article().accessStatus());
            assertEquals("text", facts.text().id());
        }
        assertEquals(Set.of("issue-0"), overlay().issueIds());
        System.out.println("AUTHORITY_QUERY_PROOF uniqueArticleVersions=258 missing=1 returnedVersions=257 registryQueries=2 maxIdentitiesPerQuery=256 repeatableRead=true readOnly=true nextReadWithdrawal=true");
    }

    private DisclosureExclusions overlay() {
        return read.execute(status -> authority.current(publication, "test"));
    }

    private void unavailable(String code) {
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, assertThrows(CustomException.class, this::overlay).getErrorCode());
        assertEquals(code, assertThrows(PublicationException.class,
                () -> read.executeWithoutResult(status -> authority.requireFullRights(publication, "test"))).code());
    }

    private static final class CountingJdbc extends NamedParameterJdbcTemplate {
        int queries;
        Runnable afterFirst = () -> {};
        CountingJdbc() { super(dataSource); }
        @Override public <T> List<T> query(String sql, SqlParameterSource parameters, RowMapper<T> rows) {
            var result = super.query(sql, parameters, rows);
            queries++;
            return result;
        }
        @Override public void query(String sql, SqlParameterSource parameters, RowCallbackHandler rows) {
            super.query(sql, parameters, rows);
            if (++queries == 1) afterFirst.run();
        }
    }
}
