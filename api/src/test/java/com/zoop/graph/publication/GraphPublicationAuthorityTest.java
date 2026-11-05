package com.zoop.graph.publication;

import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import com.zoop.common.exception.GlobalExceptionHandler;
import com.zoop.common.request.RequestIdFilter;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.json.StrictJson;
import com.zoop.document.evidence.service.DocumentReadSources;
import com.zoop.document.repository.ArtifactRow;
import com.zoop.document.repository.VersionRow;
import com.zoop.document.service.InMemoryDocumentRegistry;
import com.zoop.graph.publication.GraphPublicationReader.Contribution;
import com.zoop.graph.publication.GraphPublicationReader.Publication;
import com.zoop.graph.read.DisclosureExclusions;
import com.zoop.graph.read.GraphSnapshotFilter;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;
import static org.mockito.ArgumentMatchers.anySet;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.spy;
import static org.junit.jupiter.api.Assertions.*;

@ExtendWith(OutputCaptureExtension.class)
class GraphPublicationAuthorityTest {
    @TempDir Path temp;
    private static final Instant NOW = Instant.parse("2026-10-31T01:00:00Z");

    @Test
    void aPermittingReceiptCannotRescueAnotherApplicableDenialOnAnyPublication() throws Exception {
        var setup = setup();
        Files.writeString(setup.secondRegistry(), registry("grant-b", false));
        for (String version : List.of("old-publication", "current-publication", "future-publication")) {
            var publication = publication(version, setup.contributions());
            var overlay = setup.authority().current(publication, "test");
            assertEquals(Set.of("issue-0"), overlay.issueIds());
            assertEquals(1, overlay.articleTargets().size());
            assertEquals(0, GraphSnapshotFilter.apply(publication.snapshot(), null, overlay).issues().size());
            assertEquals("rights_denied", assertThrows(PublicationException.class,
                    () -> setup.authority().requireFullRights(publication, "test")).code());
        }
        Files.writeString(setup.secondRegistry(), registry("grant-b", true));
        assertEquals(Set.of(), setup.authority().current(publication("after-restoration", setup.contributions()), "test").issueIds());
    }

    @Test
    void sourceExclusionsPropagateAndOneLiftCannotClearAnotherOwner() throws Exception {
        var setup = setup();
        var first = setup.contributions().getFirst(); var second = setup.contributions().getLast();
        var excluded = new DisclosureExclusions(1, Set.of("issue-0"), Set.of(), Set.of());
        setup.exclusions().put(first.sourceVersionId(), excluded);
        assertEquals(Set.of("issue-0"), setup.authority().current(publication("before", setup.contributions()), "test").issueIds());
        setup.exclusions().put(second.sourceVersionId(), new DisclosureExclusions(2, Set.of("issue-0"), Set.of(), Set.of()));
        setup.exclusions().put(first.sourceVersionId(), new DisclosureExclusions(3, Set.of(), Set.of(), Set.of()));
        assertEquals(Set.of("issue-0"), setup.authority().current(publication("after", setup.contributions()), "test").issueIds());
        setup.exclusions().put(second.sourceVersionId(), new DisclosureExclusions(4, Set.of(), Set.of(), Set.of()));
        assertEquals(Set.of(), setup.authority().current(publication("future", setup.contributions()), "test").issueIds());
    }

    @Test
    void anExclusionCarriedToASourceWithoutTheIssueFiltersNothingThere() throws Exception {
        var setup = setup();
        var second = setup.contributions().getLast();
        // #55 A-14: an activation carries an exclusion to a new source whether or not it holds the id.
        setup.exclusions().put(second.sourceVersionId(), new DisclosureExclusions(5, Set.of("issue-0", "issue-absent"), Set.of(), Set.of()));
        assertEquals(Set.of("issue-0"), setup.authority().current(publication("carried", setup.contributions()), "test").issueIds());
        assertEquals(Set.of("issue-0"), setup.authority().current(publication(second.sourceVersionId(), List.of(second)), "test").issueIds(),
                "a version that is its own source too");
        setup.exclusions().put(second.sourceVersionId(), new DisclosureExclusions(6, Set.of("issue-absent"), Set.of(), Set.of()));
        assertEquals(Set.of(), setup.authority().current(publication("only-absent", setup.contributions()), "test").issueIds());
    }

    @Test
    void malformedCurrentAuthorityIsUnavailableRatherThanAnEmptyOverlay() throws Exception {
        var setup = setup(); Files.writeString(setup.secondRegistry(), "{}");
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, assertThrows(CustomException.class,
                () -> setup.authority().current(publication("version", setup.contributions()), "test")).getErrorCode());
    }

    @Test
    void currentArticleWithdrawalAlsoHidesHistoricalHeadline() throws Exception {
        var setup = setup(); var article = setup.contributions().getFirst().projection().articles().getFirst();
        setup.registry().seedArticle(article.articleId(), "news", "source", null, "withdrawn");
        assertEquals(Set.of("issue-0"), setup.authority().current(publication("historic", setup.contributions()), "test").issueIds());
    }

    @Test
    void missingTextAndDuplicateReceiptIdentitiesFailClosed() throws Exception {
        var setup = setup();
        var publication = publication("missing-text", setup.contributions());
        setup.registry().removeArtifact("text");
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, assertThrows(CustomException.class,
                () -> setup.authority().current(publication, "test")).getErrorCode());

        var restored = setup();
        var source = restored.contributions().getLast();
        var duplicate = (tools.jackson.databind.node.ObjectNode) source.bundle().node().deepCopy();
        var articles = (tools.jackson.databind.node.ArrayNode) duplicate.get("articles");
        articles.add(articles.get(0).deepCopy());
        var changed = new Contribution(source.sourceVersionId(), source.sourceId(), source.sourceKind(), source.receipt(),
                source.projectionArtifact(), source.projection(), StrictJson.Obj.of(duplicate));
        var ambiguous = publication("duplicate-identity", List.of(restored.contributions().getFirst(), changed));
        var authority = restored.authority();
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, assertThrows(CustomException.class,
                () -> authority.current(ambiguous, "test")).getErrorCode());
    }

    @ParameterizedTest
    @CsvSource({
            "missing, publication, basis_unavailable",
            "mismatch, publication, basis_mismatch",
            "receipt, receipt, receipt_invalid",
            "json, json, json_invalid",
            "registry, registry, source_registry_invalid",
            "registry-missing, registry, source_registry_unreadable",
            "registry-interrupted, registry, source_registry_unreadable",
            "unknown, publication, publication_invalid"
    })
    void authorityFailureLogsOnlyClosedReasonAndCorrelationWhileHttpStaysUnavailable(
            String scenario, String category, String reason, CapturedOutput output) throws Exception {
        var setup = setup();
        String canary = "PRIVATE_CANARY_article_prompt_grant_https://secret.invalid/private";
        var source = setup.contributions().getFirst();
        var bundle = (tools.jackson.databind.node.ObjectNode) source.bundle().node().deepCopy();
        bundle.put("private", canary);
        var article = (tools.jackson.databind.node.ObjectNode) bundle.get("articles").get(0);
        GraphPublicationAuthority authority = setup.authority();
        switch (scenario) {
            case "missing" -> setup.registry().removeArtifact("text");
            case "mismatch" -> article.put("textSha256", "0".repeat(64));
            case "receipt" -> article.putArray("observations");
            case "json" -> article.remove("textSha256");
            case "registry" -> Files.writeString(setup.secondRegistry(), "{\"private\":\"" + canary + "\"}");
            case "registry-missing" -> Files.delete(setup.secondRegistry());
            case "registry-interrupted" -> {
                var registry = spy(setup.registry());
                doAnswer(invocation -> {
                    var facts = invocation.callRealMethod();
                    Thread.currentThread().interrupt();
                    return facts;
                }).when(registry).findArticleFacts(anySet());
                authority = new GraphPublicationAuthority(registry, new DocumentReadSources(temp.toRealPath().resolve("authority.json")),
                        version -> setup.exclusions().getOrDefault(version, DisclosureExclusions.NONE), Clock.fixed(NOW, ZoneOffset.UTC));
            }
            case "unknown" -> authority = new GraphPublicationAuthority(setup.registry(), null,
                    version -> { throw new PublicationException(canary); }, Clock.fixed(NOW, ZoneOffset.UTC));
            default -> throw new AssertionError(scenario);
        }
        var changed = new Contribution(source.sourceVersionId(), source.sourceId(), source.sourceKind(), source.receipt(),
                source.projectionArtifact(), source.projection(), StrictJson.Obj.of(bundle));
        var publication = publication("synthetic-diagnostic", List.of(changed, setup.contributions().getLast()));
        var mvc = MockMvcBuilders.standaloneSetup(new AuthorityReadController(authority, publication))
                .setControllerAdvice(new GlobalExceptionHandler()).addFilters(new RequestIdFilter()).build();
        try {
            mvc.perform(get("/api/v1/graph").header(RequestIdFilter.HEADER, "synthetic-authority-read"))
                    .andExpect(status().isServiceUnavailable())
                    .andExpect(jsonPath("$.error.code").value("SOURCE_UNAVAILABLE"))
                    .andExpect(jsonPath("$.error.requestId").value("synthetic-authority-read"))
                    .andExpect(jsonPath("$.error.retryable").value(false))
                    .andExpect(jsonPath("$.error.reason").doesNotExist())
                    .andExpect(jsonPath("$.error.category").doesNotExist());
        } finally {
            Thread.interrupted();
        }
        var diagnostics = output.getAll().lines().filter(line -> line.contains("Graph publication authority unavailable")).toList();
        assertEquals(1, diagnostics.size());
        String registryDiagnostic = switch (scenario) {
            case "registry" -> ", failureKind=NOT_IO, interrupted=false";
            case "registry-missing" -> ", failureKind=NOT_FOUND, interrupted=false";
            case "registry-interrupted" -> ", failureKind=INTERRUPTED_IO, interrupted=true";
            default -> "";
        };
        assertTrue(diagnostics.getFirst().endsWith("(category=" + category + ", reason=" + reason
                + ", requestFingerprint=ea8089e3a30d2588116e612473cab14bd9ae23852720bdd63d1e3dc9e8912558"
                + registryDiagnostic + ")"));
        assertFalse(output.getAll().contains(canary));
        assertFalse(output.getAll().contains(temp.toString()));
        assertFalse(output.getAll().contains("at com.zoop.graph.publication"));
    }

    @ParameterizedTest
    @CsvSource({"missing, NOT_FOUND, false", "interrupted, INTERRUPTED_IO, true"})
    void initialRegistryFailureLogsOnlyItsKindAndCapturedInterruptState(
            String scenario, String kind, boolean interrupted, CapturedOutput output) throws Exception {
        String canary = "PRIVATE_CANARY_registry_path_and_content";
        Path file = temp.toRealPath().resolve(canary + ".json");
        Files.writeString(file, registry("grant-a", true).replace("synthetic fixture", canary));
        var sources = new DocumentReadSources(file);
        assertNull(sources.registry("synthetic-initial-read").denial("source", "grant-a", "r1", NOW));
        if ("missing".equals(scenario)) Files.delete(file);
        CustomException failure;
        try {
            if (interrupted) Thread.currentThread().interrupt();
            failure = assertThrows(CustomException.class, () -> sources.registry("synthetic-initial-read"));
            assertEquals(interrupted, Thread.currentThread().isInterrupted());
        } finally {
            Thread.interrupted();
        }
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, failure.getErrorCode());
        var diagnostics = output.getAll().lines()
                .filter(line -> line.contains("Document read ingestion source registry unavailable")).toList();
        assertEquals(1, diagnostics.size());
        assertTrue(diagnostics.getFirst().endsWith("(code=source_registry_unreadable, requestId=synthetic-initial-read"
                + ", failureKind=" + kind + ", interrupted=" + interrupted + ")"));
        assertFalse(output.getAll().contains(canary));
        assertFalse(output.getAll().contains(temp.toString()));
        assertFalse(output.getAll().contains("at com.zoop.document"));
    }

    @RestController
    private record AuthorityReadController(GraphPublicationAuthority authority, Publication publication) {
        @GetMapping("/api/v1/graph")
        DisclosureExclusions read(jakarta.servlet.http.HttpServletRequest request) {
            return authority.current(publication, RequestIdFilter.currentId(request));
        }
    }

    private record Setup(GraphPublicationAuthority authority, InMemoryDocumentRegistry registry, List<Contribution> contributions,
            Map<String, DisclosureExclusions> exclusions, Path secondRegistry) {}

    private Setup setup() throws Exception {
        Path first = temp.resolve("first.json"), second = temp.resolve("second.json"), wrapper = temp.resolve("authority.json");
        Files.writeString(first, registry("grant-a", true)); Files.writeString(second, registry("grant-b", true));
        var routes = StrictJson.newObject(); routes.put("schemaVersion", "zoop-source-authority-set-1"); var authorities = routes.putArray("authorities");
        authorities.addObject().put("sourceId", "source").put("grantId", "grant-a").put("revision", "r1").put("sources", first.toRealPath().toString());
        authorities.addObject().put("sourceId", "source").put("grantId", "grant-b").put("revision", "r1").put("sources", second.toRealPath().toString());
        Files.write(wrapper, StrictJson.write(routes));
        Contribution original = PublicationMergerTest.source(0, "issue-0", "A");
        Contribution other = PublicationMergerTest.source(1, "issue-1", "B");
        var p = original.projection(); var article = p.articles().getFirst();
        var q = new PublicGraphSnapshot(p.snapshotFormat(), other.sourceVersionId(), other.sourceId(), p.companies(), p.issues(), p.relations(), p.articles(), p.evidence());
        var a = withBundle(original, p, "grant-a"); var b = withBundle(other, q, "grant-b");
        var registry = new InMemoryDocumentRegistry(); registry.seedArticle(article.articleId(), "news", "source", null, "available");
        registry.insertArtifactIfAbsent(new ArtifactRow("text", "extracted_text", "artifact-root:extracted_text/text.txt", "f".repeat(64), 1, "text/plain", NOW));
        registry.insertVersionIfAbsent(new VersionRow(article.articleId(), article.version(), article.title(), "Publisher", article.url(), null,
                java.time.LocalDate.parse("2026-10-01"), "day", null, "text", NOW));
        Map<String, DisclosureExclusions> exclusions = new HashMap<>();
        var authority = new GraphPublicationAuthority(registry, new DocumentReadSources(wrapper.toRealPath()),
                version -> exclusions.getOrDefault(version, DisclosureExclusions.NONE), Clock.fixed(NOW, ZoneOffset.UTC));
        return new Setup(authority, registry, List.of(a, b), exclusions, second);
    }
    static Contribution withBundle(Contribution source, PublicGraphSnapshot projection, String grant) {
        var bundle = StrictJson.newObject(); var article = projection.articles().getFirst();
        var node = bundle.putArray("articles").addObject(); node.put("articleId", article.articleId()); node.put("articleVersion", article.version()); node.put("textSha256", "f".repeat(64));
        var observation = node.putArray("observations").addObject(); observation.put("sourceId", "source"); observation.putObject("grant").put("grantId", grant).put("revision", "r1");
        return new Contribution(source.sourceVersionId(), source.sourceId(), source.sourceKind(), source.receipt(), source.projectionArtifact(), projection, StrictJson.Obj.of(bundle));
    }
    static Publication publication(String version, List<Contribution> sources) {
        var merged = PublicationMerger.merge(sources, PublicationMerger.emptyDecisions(), Set.of());
        return new Publication(version, "publication", "digest", null, null, sources.getFirst().receipt(), sources.getFirst().projectionArtifact(),
                merged.snapshot(version, "publication"), sources, PublicationMerger.emptyDecisions(), merged.issueSources(), merged.relationSources());
    }
    static String registry(String grant, boolean enabled) {
        return """
                {"schemaVersion":"zoop-ingestion-s2-1","revision":"registry-1","sources":[{
                  "sourceId":"source","adapter":"authored-files","inputRoot":"/synthetic","allowedHosts":["example.invalid"],
                  "scopes":[{"scopeId":"body","selection":"synthetic fixture","initialCursor":null,"articleXPath":null,"timestampLimitations":["Synthetic publication dates are fixed test inputs."]}],
                  "grant":{"grantId":"%s","revision":"r1","sourceId":"source","enabled":%s,"rights":"known",
                    "allowedOperations":["read","store","quote-display"],"recipients":[],"purposes":[],"evidence":["synthetic fixture"],"expiresAt":null}}]}
                """.formatted(grant, enabled);
    }
}
