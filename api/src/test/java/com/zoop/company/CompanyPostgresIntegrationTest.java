package com.zoop.company;

import java.time.Instant;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;

import com.zoop.ZoopApplication;
import com.zoop.company.repository.CompanySearchPage;
import com.zoop.company.repository.CompanySearchRepository;
import com.zoop.company.repository.CompanySearchRow;
import com.zoop.company.service.CompanySearchService;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.springframework.boot.WebApplicationType;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.jdbc.core.JdbcTemplate;

import static org.junit.jupiter.api.Assertions.*;

@Tag("company-postgres")
class CompanyPostgresIntegrationTest {
    private static ConfigurableApplicationContext context;
    private static JdbcTemplate jdbc;
    private static CompanySearchService service;
    private static CompanySearchRepository repository;
    private static String url;

    @BeforeAll
    static void startApplicationAgainstDisposableDatabase() {
        url = System.getenv("ZOOP_COMPANY_TEST_DB_URL");
        if (url == null || !url.matches("jdbc:postgresql://127\\.0\\.0\\.1:[0-9]+/zoop_company_test_19")) {
            throw new IllegalStateException("Set ZOOP_COMPANY_TEST_DB_URL to the dedicated localhost zoop_company_test_19 database");
        }
        context = new SpringApplicationBuilder(ZoopApplication.class)
                .web(WebApplicationType.NONE)
                .run("--spring.datasource.url=" + url,
                        "--spring.datasource.username=company_test", "--spring.datasource.password=",
                        "--spring.jpa.hibernate.ddl-auto=validate", "--zoop.ai.client.enabled=false");
        jdbc = context.getBean(JdbcTemplate.class);
        service = context.getBean(CompanySearchService.class);
        repository = context.getBean(CompanySearchRepository.class);
    }

    @AfterAll
    static void closeApplication() {
        if (context != null) {
            context.close();
        }
    }

    @BeforeEach
    void loadSyntheticCatalog() {
        jdbc.update("DELETE FROM companies");
        jdbc.update("""
                INSERT INTO companies (id, name, ticker, exchange_code, aliases) VALUES
                ('acme', 'Zulu id', NULL, NULL, ARRAY['acme']),
                ('ticker-us', 'Yankee US', 'ACME', 'NYSE', '{}'),
                ('ticker-jp', 'Yankee JP', 'ACME', 'TSE', '{}'),
                ('name-exact', 'ACME', NULL, NULL, '{}'),
                ('alias-exact', 'A Alias', NULL, NULL, ARRAY['ACME']),
                ('partial', 'B acme group', NULL, NULL, '{}'),
                ('tie-a', 'Twin', NULL, NULL, '{}'),
                ('tie-b', 'Twin', NULL, NULL, '{}'),
                ('boundary', 'Boundary', NULL, NULL, ARRAY['foo', 'bar']),
                ('special', '100%_Lab', NULL, NULL, '{}'),
                ('short', 'X', NULL, NULL, '{}')
                """);
        jdbc.update("INSERT INTO companies (id, name) VALUES (?, ?)", "backslash", "Back\\Slash");
    }

    @Test
    void freshMigrationsAndJpaValidationSucceed() {
        assertEquals(Boolean.TRUE, jdbc.queryForObject("SELECT success FROM flyway_schema_history "
                + "WHERE version='20261013153313'", Boolean.class));
        assertEquals(1, jdbc.queryForObject("SELECT count(*) FROM pg_extension WHERE extname='pg_trgm'", Integer.class));
        assertIndex("companies_pkey", "btree", "id", true, null);
        assertIndex("uq_companies_exchange_ticker", "btree", "exchange_code, ticker", true,
                "((exchange_code IS NOT NULL) AND (ticker IS NOT NULL))");
        assertIndex("ix_companies_ticker", "btree", "ticker", false, null);
        assertIndex("ix_companies_ticker_key", "btree", "zoop_normalize_company_text(ticker)", false, null);
        assertIndex("ix_companies_name_key", "btree", "name_key", false, null);
        assertIndex("ix_companies_search_text_trgm", "gin", "search_text", false, null);
        assertEquals("gin_trgm_ops", jdbc.queryForObject("SELECT op.opcname FROM pg_index i "
                + "JOIN pg_opclass op ON op.oid=i.indclass[0] "
                + "WHERE i.indexrelid='public.ix_companies_search_text_trgm'::regclass", String.class));
        context.getBean(Flyway.class).validate();
    }

    private static void assertIndex(String name, String method, String keys, boolean unique, String predicate) {
        var index = jdbc.queryForMap("""
                SELECT am.amname, i.indisunique, i.indisvalid, i.indisready,
                       pg_get_expr(i.indpred, i.indrelid) AS predicate,
                       (SELECT string_agg(pg_get_indexdef(i.indexrelid, n, true), ', ' ORDER BY n)
                        FROM generate_series(1, i.indnkeyatts) n) AS keys
                FROM pg_index i
                JOIN pg_class c ON c.oid=i.indexrelid
                JOIN pg_am am ON am.oid=c.relam
                WHERE i.indrelid='public.companies'::regclass AND c.relname=?
                """, name);
        assertEquals(method, index.get("amname"), name);
        assertEquals(keys, index.get("keys"), name);
        assertEquals(unique, index.get("indisunique"), name);
        assertEquals(Boolean.TRUE, index.get("indisvalid"), name);
        assertEquals(Boolean.TRUE, index.get("indisready"), name);
        assertEquals(predicate, index.get("predicate"), name);
    }

    @Test
    void existingAuthSchemaCanUpgradeWithoutReapplyingOldMigrations() {
        String schema = "company_upgrade_" + java.util.UUID.randomUUID().toString().replace("-", "");
        String upgradeUrl = url + "?currentSchema=" + schema + ",public";
        Flyway baseline = Flyway.configure().dataSource(upgradeUrl, "company_test", "")
                .schemas(schema).defaultSchema(schema)
                .target("20261013000000").load();
        baseline.migrate();
        assertEquals(0, jdbc.queryForObject("SELECT count(*) FROM information_schema.tables "
                + "WHERE table_schema=? AND table_name='companies'", Integer.class, schema));
        Flyway upgrade = Flyway.configure().dataSource(upgradeUrl, "company_test", "")
                .schemas(schema).defaultSchema(schema).load();
        assertEquals(1, upgrade.migrate().migrationsExecuted);
        upgrade.validate();
        assertEquals(0, upgrade.migrate().migrationsExecuted);
        assertEquals(1, jdbc.queryForObject("SELECT count(*) FROM information_schema.tables "
                + "WHERE table_schema=? AND table_name='companies'", Integer.class, schema));
    }

    @Test
    void normalizationPreservesInteriorSpacesAndPunctuation() {
        assertEquals("acme", repository.normalize("\t\r\n\u00a0ＡＣＭＥ\u3000\n"));
        assertEquals("", repository.normalize("\t\n\r \u0085\u1680\u2028\u2029\u205f"));
        assertEquals("a  b-%_", repository.normalize("\tＡ  B-%_\n"));
        assertEquals(ids(search("acme")), ids(search("\tＡＣＭＥ\r\n")));
        assertEquals(ids(search(null)), ids(search("\t\n")));
    }

    @Test
    void exactIdentifiersThenNameThenAliasesAndPartialMatches() {
        assertEquals(List.of("ticker-jp", "ticker-us", "acme", "name-exact", "alias-exact", "partial"),
                ids(search("acme")));
        assertEquals(List.of(0, 0, 0, 1, 2, 2), search("acme").items().stream().map(CompanySearchRow::matchRank).toList());
    }

    @Test
    void oneAndTwoCharacterQueriesAndIdTickerFragmentsAreSearchable() {
        assertTrue(ids(search("x")).contains("short"));
        assertTrue(ids(search("ac")).containsAll(List.of("acme", "ticker-us", "ticker-jp", "name-exact")));
        assertTrue(ids(search("ticker-u")).contains("ticker-us"));
        assertEquals(List.of(), ids(search("no-such-company")));
    }

    @Test
    void likeMetacharactersAreLiteral() {
        assertEquals(List.of("special"), ids(search("%")));
        assertEquals(List.of("special"), ids(search("_")));
        assertEquals(List.of("backslash"), ids(search("\\")));
    }

    @Test
    void joinedAliasBoundaryIsNotARealMatch() {
        assertEquals(List.of("boundary"), ids(search("foo")));
        assertEquals(List.of(), ids(search("foo\nbar")));
    }

    @Test
    void insertAndUpdateTriggerRefreshDerivedSearchValues() {
        jdbc.update("INSERT INTO companies (id, name, aliases) VALUES (?, ?, ARRAY[?])",
                "trigger", "\tＯＬＤ\n", "\tOldAlias\r");
        assertEquals("old", jdbc.queryForObject("SELECT name_key FROM companies WHERE id='trigger'", String.class));
        assertEquals(List.of("trigger"), ids(search("oldalias")));
        jdbc.update("UPDATE companies SET name=?, aliases=ARRAY[?] WHERE id='trigger'", "\nＮＥＷ\t", "NewAlias");
        assertEquals("new", jdbc.queryForObject("SELECT name_key FROM companies WHERE id='trigger'", String.class));
        assertEquals(List.of(), ids(search("oldalias")));
        assertEquals(List.of("trigger"), ids(search("newalias")));
    }

    @Test
    void exchangeTickerUniquenessAllowsDifferentExchangesAndMissingTicker() {
        assertThrows(DataIntegrityViolationException.class, () -> jdbc.update("INSERT INTO companies "
                + "(id, name, ticker, exchange_code) VALUES ('duplicate', 'Duplicate', 'ACME', 'NYSE')"));
        jdbc.update("INSERT INTO companies (id, name, ticker, exchange_code) VALUES "
                + "('no-exchange-1', 'One', 'ACME', NULL), ('no-exchange-2', 'Two', 'ACME', NULL)");
        assertEquals(4, jdbc.queryForObject("SELECT count(*) FROM companies WHERE ticker='ACME'", Integer.class));
    }

    @Test
    void pagesHaveNoMissingOrDuplicateCompaniesIncludingTiedNames() {
        for (String query : List.of("", "acme", "Twin")) {
            List<String> expected = ids(search(query));
            List<String> actual = new ArrayList<>();
            String cursor = null;
            int pages = 0;
            do {
                CompanySearchPage page = service.search(query, cursor, 1, "graph-test", Instant.parse("2026-10-13T00:00:00Z"));
                actual.addAll(ids(page));
                cursor = page.nextCursor();
                assertTrue(++pages <= expected.size() + 1, "cursor must terminate");
            } while (cursor != null);
            assertEquals(expected, actual, query);
            assertEquals(actual.size(), new HashSet<>(actual).size());
        }
    }

    @Test
    void maximumLimitAndInvalidCursorsWorkWithRealRepository() {
        assertEquals(ids(search(null)), ids(service.search(null, null, Integer.MAX_VALUE, null, null)));
        String cursor = service.search("acme", null, 1, null, null).nextCursor();
        assertThrows(IllegalArgumentException.class, () -> service.search("other", cursor, 1, null, null));
        assertThrows(IllegalArgumentException.class, () -> service.search("acme", "!bad!", 1, null, null));
        assertThrows(IllegalArgumentException.class, () -> service.search("acme", "", 1, null, null));
    }

    private static CompanySearchPage search(String query) {
        return service.search(query, null, null, null, null);
    }

    private static List<String> ids(CompanySearchPage page) {
        return page.items().stream().map(CompanySearchRow::id).toList();
    }
}
