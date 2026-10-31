package com.zoop.graph.exclusion;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.Statement;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

import javax.sql.DataSource;

import com.zoop.ZoopApplication;
import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.common.json.StrictJson;
import com.zoop.document.repository.ArtifactRow;
import com.zoop.document.repository.DocumentRegistryRepository;
import com.zoop.graph.exclusion.ExclusionResult.VersionChange;
import com.zoop.graph.read.DisclosureExclusions;
import com.zoop.graph.read.JdbcDisclosureExclusionReader;
import com.zoop.graph.version.JdbcGraphVersionRepository;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.boot.WebApplicationType;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionSystemException;
import org.springframework.transaction.support.TransactionCallback;
import org.springframework.transaction.support.TransactionOperations;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.node.ObjectNode;
import com.zoop.ai.AiOperation;
import com.zoop.ai.AiTransportException;
import com.zoop.ai.HandoffServiceErrorException;
import com.zoop.ai.handoff.HandoffExposureClient;
import java.util.ArrayList;
import java.util.Optional;
import java.util.OptionalInt;
import java.util.function.Function;
import tools.jackson.databind.JsonNode;

/**
 * The exclusion store, its read and the operator command against the disposable company test database: real migration, constraints,
 * append-only triggers and the publication lock. Imported versions and their receipts are synthetic rows and files.
 */
@Tag("graph-postgres")
class DisclosureExclusionPostgresTest {
    private static final String HANDOFF_1 = "exclusion-test-handoff-1";
    private static final String HANDOFF_2 = "exclusion-test-handoff-2";
    /** Imported from an older bundle schema: the exposure query cannot map it. */
    private static final String HANDOFF_OLD = "exclusion-test-handoff-old";
    private static ConfigurableApplicationContext context;
    private static JdbcTemplate jdbc;
    private static DocumentRegistryRepository registry;
    private static JdbcDisclosureExclusionReader reader;

    @TempDir
    Path temp;
    private ArtifactFileStore store;
    private DisclosureExclusionService service;
    private final ExclusionRequestParser parser = new ExclusionRequestParser();
    private final String v1 = DisclosureExclusionService.versionId(HANDOFF_1);
    private final String v2 = DisclosureExclusionService.versionId(HANDOFF_2);

    @BeforeAll
    static void start() {
        String url = System.getenv("ZOOP_COMPANY_TEST_DB_URL");
        if (url == null || !url.matches("jdbc:postgresql://127\\.0\\.0\\.1:[0-9]+/zoop_company_test_19")) {
            throw new IllegalStateException("Set ZOOP_COMPANY_TEST_DB_URL to the dedicated localhost zoop_company_test_19 database");
        }
        context = new SpringApplicationBuilder(ZoopApplication.class).web(WebApplicationType.NONE)
                .run("--spring.datasource.url=" + url, "--spring.datasource.username=company_test",
                        "--spring.datasource.password=" + System.getenv().getOrDefault("ZOOP_COMPANY_TEST_DB_PASSWORD", ""),
                        "--spring.jpa.hibernate.ddl-auto=validate", "--zoop.ai.client.enabled=false",
                        "--ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test",
                        "--ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA");
        jdbc = context.getBean(JdbcTemplate.class);
        registry = context.getBean(DocumentRegistryRepository.class);
        reader = new JdbcDisclosureExclusionReader(context.getBean(NamedParameterJdbcTemplate.class));
    }

    @AfterAll
    static void stop() {
        if (jdbc != null) clean();
        if (context != null) context.close();
    }

    /** Versions go with their exclusion targets (cascade); the change log is history and stays. */
    private static void clean() {
        jdbc.update("DELETE FROM graph_versions WHERE source_label = 'exclusion-test'");
        for (String handoffId : List.of(HANDOFF_1, HANDOFF_2, HANDOFF_OLD)) {
            String versionId = DisclosureExclusionService.versionId(handoffId);
            jdbc.update("DELETE FROM artifacts WHERE id IN (?, ?)", "artifact-exclusion-test-" + versionId,
                    "artifact-receipt-" + versionId);
        }
    }

    @BeforeEach
    void setUp() throws Exception {
        clean();
        store = ArtifactFileStore.at(Files.createDirectory(temp.toRealPath().resolve("artifacts")));
        service = new DisclosureExclusionService(new JdbcDisclosureExclusionRepository(context.getBean(NamedParameterJdbcTemplate.class)),
                registry, store, new TransactionTemplate(context.getBean(PlatformTransactionManager.class)));
        stageVersion(HANDOFF_1);
        stageVersion(HANDOFF_2);
    }

    @AfterEach
    void tearDown() {
        clean();
    }

    /** An imported version as the importer leaves it: the version row and its registered, verified receipt file. */
    private void stageVersion(String handoffId) throws Exception {
        stageVersion(handoffId, DisclosureExclusionService.BUNDLE_SCHEMA);
    }

    private void stageVersion(String handoffId, String bundleSchema) throws Exception {
        String versionId = DisclosureExclusionService.versionId(handoffId);
        ObjectNode receipt = StrictJson.newObject();
        receipt.putObject("bundle").put("schemaVersion", bundleSchema);
        receipt.put("schemaVersion", "zoop-graph-handoff-import-receipt-1");
        receipt.put("handoffId", handoffId);
        receipt.put("manifestDigest", ExposureReports.DIGEST_M);
        receipt.put("bundleDigest", ExposureReports.DIGEST_B);
        receipt.put("contentDigest", ExposureReports.DIGEST_C);
        byte[] bytes = StrictJson.write(receipt);
        ArtifactFileStore.StoredFile file;
        try (ArtifactFileStore.Session session = store.open()) {
            file = session.put("verification_receipt", versionId + ".json", bytes);
        }
        registry.insertArtifactIfAbsent(new ArtifactRow("artifact-receipt-" + versionId, "verification_receipt", file.uri(),
                file.sha256(), file.bytes(), "application/json", Instant.now()));
        jdbc.update("""
                INSERT INTO artifacts (id, kind, storage_uri, sha256, bytes, media_type, created_at)
                VALUES (?, 'graph_snapshot', ?, ?, 1, 'application/json', now())
                """, "artifact-exclusion-test-" + versionId, "artifact:exclusion-test-" + versionId, "0".repeat(64));
        jdbc.update("""
                INSERT INTO graph_versions (id, sequence, kind, created_at, created_by, source_label, issue_count,
                    relation_count, article_count, snapshot_artifact_id, review_revision)
                VALUES (?, (SELECT COALESCE(MAX(sequence), 0) + 1 FROM graph_versions), 'snapshot', now(), 'operator:test',
                    'exclusion-test', 1, 1, 1, ?, 0)
                """, versionId, "artifact-exclusion-test-" + versionId);
    }

    private ExclusionResult run(byte[] request) {
        return service.run(parser.parse(request));
    }

    /** What an activation does under the publication lock in its transaction: carry {@code base}'s exclusions to {@code target}. */
    private int carry(String base, String target) {
        JdbcDisclosureExclusionRepository repository = new JdbcDisclosureExclusionRepository(
                context.getBean(NamedParameterJdbcTemplate.class));
        return new TransactionTemplate(context.getBean(PlatformTransactionManager.class)).execute(status -> {
            repository.lockPublication();
            return new DisclosureExclusionCarry(repository).carry(base, target, "system");
        });
    }

    private long revision() {
        return jdbc.queryForObject("SELECT COALESCE(MAX(revision), 0) FROM disclosure_exclusion_changes", Long.class);
    }

    /** Stands in for the AI exposure query: records what it was asked, then answers or fails. */
    private static final class FakeExposure implements HandoffExposureClient {
        final List<List<String>> asked = new ArrayList<>();
        Function<List<String>, JsonNode> answer = ids -> {
            throw new AssertionError("not asked");
        };
        RuntimeException failure;

        @Override
        public JsonNode exposure(List<String> handoffIds, JsonNode changed) {
            asked.add(List.copyOf(handoffIds));
            if (failure != null) throw failure;
            return answer.apply(handoffIds);
        }
    }

    private DisclosureExclusionService querying(HandoffExposureClient exposure) {
        return new DisclosureExclusionService(new JdbcDisclosureExclusionRepository(context.getBean(NamedParameterJdbcTemplate.class)),
                registry, store, new TransactionTemplate(context.getBean(PlatformTransactionManager.class)), exposure);
    }

    private ExclusionFailure failure(DisclosureExclusionService with, byte[] request) {
        ExclusionResult result = with.run(parser.parse(request));
        assertFalse(result.succeeded());
        return result.failure().failure();
    }

    @Test
    void aQueryAsksTheHandoffsOfTheNamedVersionsAndExcludesWhatTheAnswerProposesOnce() {
        FakeExposure fake = new FakeExposure();
        fake.answer = ids -> ExposureReports.report(ExposureReports.handoff(HANDOFF_1, List.of("issue-q"), List.of(), false),
                ExposureReports.handoff(HANDOFF_2, List.of(), List.of(), false));
        byte[] request = ExposureReports.query(ExposureReports.requestId(), ExposureReports.sourceChange(), v1, v2);

        ExclusionResult result = querying(fake).run(parser.parse(request));

        assertTrue(result.succeeded(), () -> String.valueOf(result.failure()));
        assertEquals(ExclusionResult.APPLIED, result.outcome());
        assertEquals(List.of(List.of(HANDOFF_1, HANDOFF_2)), fake.asked, "the handoff ids the receipts name, in that order");
        assertEquals(Set.of("issue-q"), reader.current(v1).issueIds());
        assertEquals(Set.of(), reader.current(v2).issueIds());

        ExclusionResult again = querying(fake).run(parser.parse(request));
        assertTrue(again.replay(), "the recorded result");
        assertEquals(1, fake.asked.size(), "a recorded request asks nothing again");
    }

    @Test
    void anAnswerAboutSomethingElseARefusalOrNoClientWritesNothing() {
        long before = revision();
        FakeExposure fake = new FakeExposure();
        fake.answer = ids -> ExposureReports.report(ExposureReports.handoff(HANDOFF_2, List.of("issue-x"), List.of(), false));
        assertEquals(ExclusionFailure.REPORT_INVALID,
                failure(querying(fake), ExposureReports.query(ExposureReports.requestId(), ExposureReports.sourceChange(), v1)),
                "an answer for other handoffs than asked");

        fake.answer = ids -> ExposureReports.report(ExposureReports.handoff(HANDOFF_1, List.of("issue-x"), List.of(), false));
        ObjectNode otherChange = ExposureReports.sourceChange();
        otherChange.put("sourceId", "another-source");
        assertEquals(ExclusionFailure.REPORT_INVALID,
                failure(querying(fake), ExposureReports.query(ExposureReports.requestId(), otherChange, v1)),
                "an answer for another change than asked");

        fake.failure = new HandoffServiceErrorException(AiOperation.EXPOSURE, "req-1", 403, "handoff_not_allowed", false,
                Optional.empty(), Optional.empty(), Optional.empty());
        assertEquals(ExclusionFailure.EXPOSURE_REFUSED,
                failure(querying(fake), ExposureReports.query(ExposureReports.requestId(), ExposureReports.sourceChange(), v1)));
        fake.failure = new HandoffServiceErrorException(AiOperation.EXPOSURE, "req-1", 409, "handoff_pin_mismatch", false,
                Optional.empty(), Optional.empty(), Optional.empty());
        assertEquals(ExclusionFailure.EXPOSURE_REFUSED,
                failure(querying(fake), ExposureReports.query(ExposureReports.requestId(), ExposureReports.sourceChange(), v1)));
        fake.failure = new HandoffServiceErrorException(AiOperation.EXPOSURE, "req-1", 503, "runtime_busy", true,
                Optional.empty(), Optional.empty(), Optional.empty());
        assertEquals(ExclusionFailure.EXPOSURE_UNAVAILABLE,
                failure(querying(fake), ExposureReports.query(ExposureReports.requestId(), ExposureReports.sourceChange(), v1)),
                "a 5xx envelope is the service being unavailable, not a refusal");
        fake.failure = new AiTransportException(AiOperation.EXPOSURE, "req-1", AiTransportException.Failure.TIMEOUT,
                OptionalInt.empty(), "HttpTimeoutException");
        assertEquals(ExclusionFailure.EXPOSURE_UNAVAILABLE,
                failure(querying(fake), ExposureReports.query(ExposureReports.requestId(), ExposureReports.sourceChange(), v1)));
        assertEquals(ExclusionFailure.EXPOSURE_UNAVAILABLE,
                failure(querying(null), ExposureReports.query(ExposureReports.requestId(), ExposureReports.sourceChange(), v1)));
        assertEquals(ExclusionFailure.VERSION_UNKNOWN, failure(querying(new FakeExposure()),
                ExposureReports.query(ExposureReports.requestId(), ExposureReports.sourceChange(), "gv-not-imported")));
        assertEquals(before, revision(), "no failed query wrote a change");
    }

    @Test
    void byDefaultTheImportedVersionsThatMayStillBecomePublicAreAskedAndAnOlderBundleIsLeftOut() throws Exception {
        stageVersion(HANDOFF_OLD, "zoop-graph-handoff-bundle-5");
        List<String> targets = new JdbcDisclosureExclusionRepository(context.getBean(NamedParameterJdbcTemplate.class))
                .exposureTargets();
        assertTrue(targets.containsAll(List.of(v1, v2)), "imported after the active version and not active");
        assertTrue(targets.indexOf(v1) < targets.indexOf(v2), "in import order");

        FakeExposure fake = new FakeExposure();
        fake.answer = ids -> ExposureReports.report(ids.stream()
                .map(id -> ExposureReports.handoff(id, HANDOFF_1.equals(id) ? List.of("issue-d") : List.of(), List.of(), false))
                .toArray(ObjectNode[]::new));
        ExclusionResult result = querying(fake).run(parser.parse(
                ExposureReports.query(ExposureReports.requestId(), ExposureReports.sourceChange())));

        assertTrue(result.succeeded(), () -> String.valueOf(result.failure()));
        assertTrue(fake.asked.getFirst().containsAll(List.of(HANDOFF_1, HANDOFF_2)));
        assertFalse(fake.asked.getFirst().contains(HANDOFF_OLD), "the AI cannot map an older bundle: never asked by default");
        assertEquals(Set.of("issue-d"), reader.current(v1).issueIds());
        // Named explicitly, it is refused before anything is asked.
        assertEquals(ExclusionFailure.VERSIONS_INVALID, failure(querying(fake), ExposureReports.query(ExposureReports.requestId(),
                ExposureReports.sourceChange(), DisclosureExclusionService.versionId(HANDOFF_OLD))));
        assertEquals(1, fake.asked.size());
    }

    /** The real producer's answer: one handoff per id, sorted by id whatever order they were asked in. */
    private static JsonNode sortedAnswer(List<String> ids, String excludedIn, String issueId) {
        return ExposureReports.report(ids.stream().sorted()
                .map(id -> ExposureReports.handoff(id, id.equals(excludedIn) ? List.of(issueId) : List.of(), List.of(), false))
                .toArray(ObjectNode[]::new));
    }

    @Test
    void theProducersSortedAnswerMatchesVersionsAskedInAnotherOrder() throws Exception {
        FakeExposure fake = new FakeExposure();
        fake.answer = ids -> sortedAnswer(ids, HANDOFF_1, "issue-sorted");
        // Named in reverse id order: asked that way, answered sorted.
        ExclusionResult named = querying(fake).run(parser.parse(
                ExposureReports.query(ExposureReports.requestId(), ExposureReports.sourceChange(), v2, v1)));
        assertTrue(named.succeeded(), () -> String.valueOf(named.failure()));
        assertEquals(List.of(HANDOFF_2, HANDOFF_1), fake.asked.getFirst());
        assertEquals(Set.of("issue-sorted"), reader.current(v1).issueIds());

        // Imported after the others but first by id: the default (import) order is not the answer's order either.
        String early = "exclusion-test-handoff-0";
        stageVersion(early);
        try {
            ExclusionResult byDefault = querying(fake).run(parser.parse(
                    ExposureReports.query(ExposureReports.requestId(), ExposureReports.sourceChange())));
            assertTrue(byDefault.succeeded(), () -> String.valueOf(byDefault.failure()));
            assertEquals(List.of(HANDOFF_1, HANDOFF_2, early), fake.asked.get(1), "asked in import order");
        } finally {
            dropVersion(early);
        }
    }

    @Test
    void oneVersionMoreThanAQueryCanSelectStopsBeforeReadingAnyFurtherReceipt() throws Exception {
        List<String> extra = new ArrayList<>();
        for (int i = 1; i <= 20; i++) extra.add("exclusion-test-cap-" + String.format("%02d", i));
        try {
            for (String handoffId : extra) stageVersion(handoffId);
            // The 22nd default target's receipt is gone: reading it would be receipt_unavailable, so stopping at the 21st shows.
            jdbc.update("DELETE FROM artifacts WHERE id = ?", "artifact-receipt-" + DisclosureExclusionService.versionId(extra.getLast()));
            FakeExposure fake = new FakeExposure();
            assertEquals(ExclusionFailure.VERSIONS_INVALID,
                    failure(querying(fake), ExposureReports.query(ExposureReports.requestId(), ExposureReports.sourceChange())));
            assertEquals(List.of(), fake.asked);
        } finally {
            for (String handoffId : extra) dropVersion(handoffId);
        }
    }

    private void dropVersion(String handoffId) {
        String versionId = DisclosureExclusionService.versionId(handoffId);
        jdbc.update("DELETE FROM graph_versions WHERE id = ?", versionId);
        jdbc.update("DELETE FROM artifacts WHERE id IN (?, ?)", "artifact-exclusion-test-" + versionId, "artifact-receipt-" + versionId);
    }

    @Test
    void theSameRequestOverAnotherSetOfVersionsIsAnotherCommand() throws Exception {
        FakeExposure fake = new FakeExposure();
        fake.answer = ids -> ExposureReports.report(ids.stream()
                .map(id -> ExposureReports.handoff(id, List.of(), List.of(), false)).toArray(ObjectNode[]::new));
        byte[] request = ExposureReports.query(ExposureReports.requestId(), ExposureReports.sourceChange());
        assertTrue(querying(fake).run(parser.parse(request)).succeeded());
        assertTrue(querying(fake).run(parser.parse(request)).replay(), "same versions: the recorded result");

        stageVersion("exclusion-test-handoff-3");
        try {
            assertEquals(ExclusionFailure.REQUEST_CONFLICT, failure(querying(fake), request),
                    "a version imported meanwhile: the recorded command covered other versions");
            assertEquals(1, fake.asked.size(), "neither re-run asked again");
        } finally {
            String extra = DisclosureExclusionService.versionId("exclusion-test-handoff-3");
            jdbc.update("DELETE FROM graph_versions WHERE id = ?", extra);
            jdbc.update("DELETE FROM artifacts WHERE id IN (?, ?)", "artifact-exclusion-test-" + extra, "artifact-receipt-" + extra);
        }
    }

    @Test
    void theOperatorCommandWiresTheExposureClientAndWritesTheResultFile() throws Exception {
        FakeExposure fake = new FakeExposure();
        fake.answer = ids -> ExposureReports.report(ids.stream()
                .map(id -> ExposureReports.handoff(id, HANDOFF_1.equals(id) ? List.of("issue-r") : List.of(), List.of(), false))
                .toArray(ObjectNode[]::new));
        Path requestFile = temp.resolve("request.json");
        Path resultFile = temp.resolve("result.json");
        Files.write(requestFile, ExposureReports.query(ExposureReports.requestId(), ExposureReports.sourceChange(), v1));
        var properties = new DisclosureExclusionConfiguration.Properties(true, requestFile.toString(), resultFile.toString(),
                temp.toRealPath().resolve("artifacts").toString());
        var exposure = new org.springframework.beans.factory.support.StaticListableBeanFactory(java.util.Map.of("exposure", fake))
                .getBeanProvider(HandoffExposureClient.class);

        new DisclosureExclusionConfiguration().disclosureExclusionRunner(properties, context,
                new JdbcDisclosureExclusionRepository(context.getBean(NamedParameterJdbcTemplate.class)), registry,
                new TransactionTemplate(context.getBean(PlatformTransactionManager.class)), exposure).run(null);

        assertEquals("applied", StrictJson.parseObject(Files.readAllBytes(resultFile)).string("outcome"));
        assertEquals(List.of(List.of(HANDOFF_1)), fake.asked);
        assertEquals(Set.of("issue-r"), reader.current(v1).issueIds());
    }

    @Test
    void aReportExcludesItsIdsInTheImportedVersionOnlyAndTheSameReportAgainChangesNothing() {
        long before = revision();
        ObjectNode report = ExposureReports.report(
                ExposureReports.handoff(HANDOFF_1, List.of("issue-a"), List.of("edge-a"), true),
                ExposureReports.handoff(HANDOFF_2, List.of(), List.of(), false));

        ExclusionResult result = run(ExposureReports.exclude(report));

        assertTrue(result.succeeded(), () -> String.valueOf(result.failure()));
        assertEquals(ExclusionResult.APPLIED, result.outcome());
        assertEquals(before + 1, result.revision());
        DisclosureExclusions first = reader.current(v1);
        assertEquals(result.revision(), first.revision());
        assertEquals(Set.of("issue-a"), first.issueIds());
        assertEquals(Set.of("edge-a"), first.relationIds());
        assertEquals(Set.of(ExposureReports.EVIDENCE), first.evidenceIds());
        assertEquals(Set.of(new DisclosureExclusions.ArticleTarget(ExposureReports.ARTICLE, ExposureReports.ARTICLE_VERSION)),
                first.articleTargets());
        // Per version: the same ids in another version (a corrected handoff may reuse them) are untouched.
        DisclosureExclusions other = reader.current(v2);
        assertEquals(Set.of(), other.issueIds());
        assertEquals(result.revision(), other.revision(), "the revision is app-wide");
        assertEquals(1, jdbc.queryForObject("SELECT count(*) FROM disclosure_exclusion_targets WHERE graph_version_id = ? "
                + "AND target_kind = 'article' AND article_version = ?", Integer.class, v1, ExposureReports.ARTICLE_VERSION),
                "article targets are recorded with their exact version for company document filtering");
        assertEquals(Map.of("article", 1, "evidence", 1, "issue", 1, "relation", 1), result.versions().get(0).changed());

        ExclusionResult again = run(ExposureReports.exclude(report.deepCopy()));
        assertEquals(ExclusionResult.UNCHANGED, again.outcome());
        assertEquals(result.revision(), revision(), "no second change for targets already excluded");
        assertEquals(Map.of("article", 1, "evidence", 1, "issue", 1, "relation", 1), again.versions().get(0).unchanged());
    }

    @Test
    void aSmallerOrEmptyReportNeverLiftsAndOnlyAnExplicitLiftDoes() {
        run(ExposureReports.exclude(ExposureReports.report(
                ExposureReports.handoff(HANDOFF_1, List.of("issue-a", "issue-b"), List.of(), false))));
        long excludedAt = revision();

        for (ObjectNode smaller : List.of(
                ExposureReports.report(ExposureReports.handoff(HANDOFF_1, List.of("issue-a"), List.of(), false)),
                ExposureReports.report(ExposureReports.handoff(HANDOFF_1, List.of(), List.of(), false)))) {
            assertEquals(ExclusionResult.UNCHANGED, run(ExposureReports.exclude(smaller)).outcome());
            assertEquals(Set.of("issue-a", "issue-b"), reader.current(v1).issueIds(), "rule 4: never narrowed by a report");
        }
        assertEquals(excludedAt, revision());

        ExclusionResult lifted = run(ExposureReports.lift(v1, revision(), "issue-a", "issue-never"));
        assertEquals(ExclusionResult.APPLIED, lifted.outcome());
        assertEquals(excludedAt + 1, lifted.revision());
        assertEquals(Map.of("issue", 1), lifted.versions().get(0).changed());
        assertEquals(Map.of("issue", 1), lifted.versions().get(0).unchanged(), "a target that was not excluded is reported");
        assertEquals(Set.of("issue-b"), reader.current(v1).issueIds());

        assertEquals(ExclusionResult.UNCHANGED, run(ExposureReports.lift(v1, revision(), "issue-a")).outcome(),
                "lifting twice is a no-op");
        // A later report may exclude a lifted target again: the latest change of a target decides.
        assertEquals(ExclusionResult.APPLIED, run(ExposureReports.exclude(ExposureReports.report(
                ExposureReports.handoff(HANDOFF_1, List.of("issue-a"), List.of(), false)))).outcome());
        assertEquals(Set.of("issue-a", "issue-b"), reader.current(v1).issueIds());
    }

    /** What an activation appends (#55 A-14): the public version's unlifted targets, once, as a carried change on the new version. */
    @Test
    void aCarryAppendsThePublicVersionsUnliftedTargetsOnceAndNothingWhenThereIsNothingNew() {
        run(ExposureReports.exclude(ExposureReports.report(
                ExposureReports.handoff(HANDOFF_1, List.of("issue-a", "issue-b"), List.of("edge-a"), true))));
        run(ExposureReports.lift(v1, revision(), "issue-b"));
        long before = revision();

        assertEquals(4, carry(v1, v2), "issue-a, edge-a, the evidence and the article; not the lifted issue-b");

        assertEquals(before + 1, revision());
        DisclosureExclusions carried = reader.current(v2);
        assertEquals(Set.of("issue-a"), carried.issueIds());
        assertEquals(Set.of("edge-a"), carried.relationIds());
        assertEquals(Set.of(ExposureReports.EVIDENCE), carried.evidenceIds());
        assertEquals(Set.of(new DisclosureExclusions.ArticleTarget(ExposureReports.ARTICLE, ExposureReports.ARTICLE_VERSION)),
                carried.articleTargets());
        assertEquals(Set.of("issue-a"), reader.current(v1).issueIds(), "the base version is untouched");
        var change = jdbc.queryForMap("SELECT action, cause, report_sha256, base_version_id, operator, reason "
                + "FROM disclosure_exclusion_changes WHERE revision = ?", before + 1);
        assertEquals("exclude", change.get("action"));
        assertEquals(DisclosureExclusionCarry.CAUSE, change.get("cause"));
        assertNull(change.get("report_sha256"));
        assertEquals(v1, change.get("base_version_id"));
        assertEquals("system", change.get("operator"));
        assertEquals("carried from " + v1 + " at activation by system", change.get("reason"));

        assertEquals(0, carry(v1, v2), "everything is already excluded there");
        assertEquals(0, carry(v2, v2), "a re-activation of the public version");
        assertEquals(0, carry(null, v2), "a first activation has no public version");
        assertEquals(before + 1, revision(), "nothing appended for nothing");

        // A lift the operator made on the new version itself (its corrected content, released while the version waited) stands:
        // the carry does not re-exclude over that decision. The base version keeps its own exclusion.
        run(ExposureReports.lift(v2, revision(), "issue-a"));
        assertEquals(0, carry(v1, v2));
        assertEquals(Set.of(), reader.current(v2).issueIds());
        assertEquals(Set.of("issue-a"), reader.current(v1).issueIds());

        // The schema keeps a carried change apart from an operator exclude: no report hash, a base version.
        assertThrows(DataAccessException.class, () -> jdbc.update("INSERT INTO disclosure_exclusion_changes "
                + "(revision, action, cause, report_sha256, reason, operator, changed_at) VALUES (?, 'exclude', 'carried', NULL, "
                + "'x', 'system', now())", revision() + 1), "a carried change without its base version");
        assertThrows(DataAccessException.class, () -> jdbc.update("INSERT INTO disclosure_exclusion_changes "
                + "(revision, action, cause, report_sha256, base_version_id, reason, operator, changed_at) VALUES (?, 'exclude', "
                + "'source-change', ?, ?, 'x', 'system', now())", revision() + 1, "9".repeat(64), v1),
                "an operator exclude never names a base version");
    }

    @Test
    void aLiftCoversTheLaterImportedVersionsOnlyWhenAskedAndTheStaleCheckSpansThem() {
        run(ExposureReports.exclude(ExposureReports.report(
                ExposureReports.handoff(HANDOFF_1, List.of("issue-a"), List.of(), false),
                ExposureReports.handoff(HANDOFF_2, List.of("issue-a"), List.of(), false))));

        ExclusionResult one = run(ExposureReports.lift(v1, revision(), "issue-a"));
        assertEquals(ExclusionResult.APPLIED, one.outcome());
        assertEquals(List.of(v1), one.versions().stream().map(VersionChange::graphVersionId).toList(), "by default the named version");
        assertEquals(Set.of("issue-a"), reader.current(v2).issueIds());

        run(ExposureReports.exclude(ExposureReports.report(ExposureReports.handoff(HANDOFF_1, List.of("issue-a"), List.of(), false))));
        ExclusionResult both = run(ExposureReports.lift(v1, revision(), true, "issue-a", "issue-never"));
        assertEquals(ExclusionResult.APPLIED, both.outcome());
        assertEquals(List.of(v1, v2), both.versions().stream().map(VersionChange::graphVersionId).toList(),
                "v2 was imported after v1: lifted there too");
        assertEquals(Map.of("issue", 1), both.versions().get(1).changed());
        assertEquals(Map.of("issue", 1), both.versions().get(1).unchanged());
        assertEquals(Set.of(), reader.current(v1).issueIds());
        assertEquals(Set.of(), reader.current(v2).issueIds());
        assertEquals(2, jdbc.queryForObject("SELECT count(*) FROM disclosure_exclusion_targets WHERE revision = ?", Integer.class,
                both.revision()), "one change, a target row per version");

        // An operator change of the target in a later version after the decision makes a lift over later versions stale, and
        // only that lift: the named version alone can still be lifted.
        run(ExposureReports.exclude(ExposureReports.report(ExposureReports.handoff(HANDOFF_1, List.of("issue-a"), List.of(), false))));
        long seen = revision();
        run(ExposureReports.exclude(ExposureReports.report(ExposureReports.handoff(HANDOFF_2, List.of("issue-a"), List.of(), false))));
        assertEquals(ExclusionFailure.REVISION_STALE, run(ExposureReports.lift(v1, seen, true, "issue-a")).failure().failure());
        assertEquals(Set.of("issue-a"), reader.current(v1).issueIds(), "nothing written");
        assertEquals(ExclusionResult.APPLIED, run(ExposureReports.lift(v1, seen, false, "issue-a")).outcome());
        assertEquals(Set.of("issue-a"), reader.current(v2).issueIds(), "the later version keeps its own exclusion");

        // A carry from the named version to a later one after the decision is not a change the operator did not see: it copied
        // the decision the lift is about. The round in between does not make the lift stale.
        run(ExposureReports.exclude(ExposureReports.report(ExposureReports.handoff(HANDOFF_1, List.of("issue-c"), List.of(), false))));
        long decided = revision();
        assertEquals(1, carry(v1, v2), "issue-c reaches v2 by the carry alone");
        ExclusionResult acrossTheCarry = run(ExposureReports.lift(v1, decided, true, "issue-c"));
        assertEquals(ExclusionResult.APPLIED, acrossTheCarry.outcome(), () -> String.valueOf(acrossTheCarry.failure()));
        assertEquals(List.of(v1, v2), acrossTheCarry.versions().stream().map(VersionChange::graphVersionId).toList());
        assertEquals(Map.of("issue", 1), acrossTheCarry.versions().get(1).changed());
        assertFalse(reader.current(v2).issueIds().contains("issue-c"));
        // The last imported version has nothing after it.
        ExclusionResult last = run(ExposureReports.lift(v2, revision(), true, "issue-a"));
        assertEquals(List.of(v2), last.versions().stream().map(VersionChange::graphVersionId).toList());
    }

    @Test
    void aReportThatDoesNotMatchTheImportedReceiptOrVersionWritesNothing() {
        long before = revision();
        ObjectNode otherImport = ExposureReports.handoff(HANDOFF_2, List.of("issue-a"), List.of(), false);
        otherImport.put("contentDigest", "d".repeat(64));

        ExclusionResult mismatch = run(ExposureReports.exclude(ExposureReports.report(
                ExposureReports.handoff(HANDOFF_1, List.of("issue-a"), List.of(), false), otherImport)));
        assertEquals(ExclusionFailure.RECEIPT_MISMATCH, mismatch.failure().failure(), "rule 1: content digest of another import");

        ExclusionResult unknown = run(ExposureReports.exclude(ExposureReports.report(
                ExposureReports.handoff("exclusion-test-never-imported", List.of("issue-a"), List.of(), false))));
        assertEquals(ExclusionFailure.VERSION_UNKNOWN, unknown.failure().failure());
        assertEquals(ExclusionFailure.VERSION_UNKNOWN, run(ExposureReports.lift("gv-none", 0, "issue-a")).failure().failure());

        assertEquals(before, revision(), "the whole report is refused: nothing of the matching handoff is written either");
        assertEquals(Set.of(), reader.current(v1).issueIds());
    }

    @Test
    void theHistoryIsAppendOnlyAndAVersionTakesItsTargetsWithIt() {
        ExclusionResult result = run(ExposureReports.exclude(ExposureReports.report(
                ExposureReports.handoff(HANDOFF_1, List.of("issue-a"), List.of(), false))));
        long revision = result.revision();

        assertThrows(DataAccessException.class, () -> jdbc.update(
                "UPDATE disclosure_exclusion_changes SET reason = 'x' WHERE revision = ?", revision));
        assertThrows(DataAccessException.class, () -> jdbc.update(
                "DELETE FROM disclosure_exclusion_changes WHERE revision = ?", revision));
        assertThrows(DataAccessException.class, () -> jdbc.update(
                "UPDATE disclosure_exclusion_targets SET target_id = 'issue-z' WHERE revision = ?", revision));
        assertThrows(DataAccessException.class, () -> jdbc.update(
                "DELETE FROM disclosure_exclusion_targets WHERE revision = ?", revision));
        assertThrows(DataAccessException.class, () -> jdbc.update(
                "UPDATE disclosure_exclusion_requests SET result = '{}'::jsonb WHERE revision = ?", revision));
        assertThrows(DataAccessException.class, () -> jdbc.update(
                "DELETE FROM disclosure_exclusion_requests WHERE revision = ?", revision));

        jdbc.update("DELETE FROM graph_versions WHERE id = ?", v1);
        assertEquals(0, jdbc.queryForObject("SELECT count(*) FROM disclosure_exclusion_targets WHERE graph_version_id = ?",
                Integer.class, v1));
        assertEquals(1, jdbc.queryForObject("SELECT count(*) FROM disclosure_exclusion_changes WHERE revision = ?",
                Integer.class, revision), "the change itself is history");
    }

    /** The review's sequence: exclude X, lift L whose result is lost, X excluded again, L re-run. */
    @Test
    void aReRunOfARecordedLiftReturnsItsResultAndNeverLiftsALaterExclusion() {
        run(ExposureReports.exclude(ExposureReports.report(ExposureReports.handoff(HANDOFF_1, List.of("issue-a"), List.of(), false))));
        byte[] lift = ExposureReports.lift(v1, revision(), "issue-a");
        ExclusionResult first = run(lift);
        assertEquals(ExclusionResult.APPLIED, first.outcome());
        run(ExposureReports.exclude(ExposureReports.report(ExposureReports.handoff(HANDOFF_1, List.of("issue-a"), List.of(), false))));
        long excludedAgain = revision();

        ExclusionResult rerun = run(lift);

        assertTrue(rerun.succeeded(), () -> String.valueOf(rerun.failure()));
        assertTrue(rerun.replay());
        assertEquals(ExclusionResult.APPLIED, rerun.outcome(), "the recorded outcome of the first run");
        assertEquals(first.revision(), rerun.revision());
        assertEquals(excludedAgain, revision(), "nothing written");
        assertEquals(Set.of("issue-a"), reader.current(v1).issueIds(), "the later exclusion stands");
        ObjectNode document = (ObjectNode) StrictJson.parseObject(ExclusionResultWriter.toBytes(rerun)).node();
        assertTrue(document.get("replayed").booleanValue());
        assertEquals(1, document.get("versions").get(0).get("changed").get("issue").intValue());
    }

    @Test
    void aLiftDecidedBeforeTheTargetLastChangedIsStale() {
        run(ExposureReports.exclude(ExposureReports.report(ExposureReports.handoff(HANDOFF_1, List.of("issue-a"), List.of(), false))));
        long seen = revision();
        run(ExposureReports.lift(v1, seen, "issue-a"));
        run(ExposureReports.exclude(ExposureReports.report(ExposureReports.handoff(HANDOFF_1, List.of("issue-a"), List.of(), false))));
        long before = revision();

        assertEquals(ExclusionFailure.REVISION_STALE, run(ExposureReports.lift(v1, seen, "issue-a")).failure().failure());
        assertEquals(ExclusionFailure.REVISION_STALE, run(ExposureReports.lift(v1, before + 1, "issue-a")).failure().failure(),
                "a revision the store has not reached");
        assertEquals(before, revision());
        assertEquals(Set.of("issue-a"), reader.current(v1).issueIds());
        // A change of another target after the decision does not make it stale.
        run(ExposureReports.exclude(ExposureReports.report(ExposureReports.handoff(HANDOFF_2, List.of("issue-z"), List.of(), false))));
        assertEquals(ExclusionResult.APPLIED, run(ExposureReports.lift(v1, before, "issue-a")).outcome());
    }

    @Test
    void theSameRequestIdForAnotherRequestIsRefused() {
        String id = ExposureReports.requestId();
        run(ExposureReports.exclude(id, ExposureReports.report(
                ExposureReports.handoff(HANDOFF_1, List.of("issue-a"), List.of(), false))));
        long before = revision();

        ExclusionResult other = run(ExposureReports.exclude(id, ExposureReports.report(
                ExposureReports.handoff(HANDOFF_1, List.of("issue-b"), List.of(), false))));

        assertEquals(ExclusionFailure.REQUEST_CONFLICT, other.failure().failure());
        assertEquals(before, revision());
        assertEquals(Set.of("issue-a"), reader.current(v1).issueIds());
    }

    @Test
    void aCommitWhoseOutcomeIsUnknownIsReportedAsSuchAndTheReRunReadsTheRecordedResult() {
        TransactionTemplate real = new TransactionTemplate(context.getBean(PlatformTransactionManager.class));
        TransactionOperations lostCommitReply = new TransactionOperations() {
            @Override
            public <T> T execute(TransactionCallback<T> action) {
                real.execute(action);
                throw new TransactionSystemException("commit reply lost");
            }
        };
        DisclosureExclusionService unsure = new DisclosureExclusionService(
                new JdbcDisclosureExclusionRepository(context.getBean(NamedParameterJdbcTemplate.class)), registry, store,
                lostCommitReply);
        byte[] request = ExposureReports.exclude(ExposureReports.report(
                ExposureReports.handoff(HANDOFF_1, List.of("issue-a"), List.of(), false)));

        ExclusionResult unknown = unsure.run(parser.parse(request));
        assertEquals(ExclusionFailure.OUTCOME_UNKNOWN, unknown.failure().failure(), "not database_unavailable: it did commit");
        long committed = revision();

        ExclusionResult rerun = run(request);
        assertTrue(rerun.replay());
        assertEquals(ExclusionResult.APPLIED, rerun.outcome());
        assertEquals(committed, rerun.revision());
        assertEquals(committed, revision());
    }

    @Test
    void aChangeWaitsForThePublicationLockWhileTheReadNeverDoes() throws Exception {
        ExecutorService pool = Executors.newSingleThreadExecutor();
        try (Connection other = context.getBean(DataSource.class).getConnection(); Statement statement = other.createStatement()) {
            // Held as a rule switch, a review decision or an activation would hold it.
            statement.execute("SELECT pg_advisory_lock(" + JdbcGraphVersionRepository.PUBLICATION_LOCK + ")");
            Future<ExclusionResult> running = pool.submit(() -> run(ExposureReports.exclude(ExposureReports.report(
                    ExposureReports.handoff(HANDOFF_1, List.of("issue-a"), List.of(), false)))));
            Thread.sleep(1000);
            assertFalse(running.isDone(), "the change waits for the lock");
            assertEquals(Set.of(), reader.current(v1).issueIds(), "the read does not wait and sees the committed state");
            statement.execute("SELECT pg_advisory_unlock(" + JdbcGraphVersionRepository.PUBLICATION_LOCK + ")");
            assertEquals(ExclusionResult.APPLIED, running.get(30, TimeUnit.SECONDS).outcome());
            assertEquals(Set.of("issue-a"), reader.current(v1).issueIds());
        } finally {
            pool.shutdownNow();
        }
    }
}
