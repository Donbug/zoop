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
import org.junit.jupiter.api.io.TempDir;
import static org.junit.jupiter.api.Assertions.*;

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
    private static Contribution withBundle(Contribution source, PublicGraphSnapshot projection, String grant) {
        var bundle = StrictJson.newObject(); var article = projection.articles().getFirst();
        var node = bundle.putArray("articles").addObject(); node.put("articleId", article.articleId()); node.put("articleVersion", article.version()); node.put("textSha256", "f".repeat(64));
        var observation = node.putArray("observations").addObject(); observation.put("sourceId", "source"); observation.putObject("grant").put("grantId", grant).put("revision", "r1");
        return new Contribution(source.sourceVersionId(), source.sourceId(), source.sourceKind(), source.receipt(), source.projectionArtifact(), projection, StrictJson.Obj.of(bundle));
    }
    private static Publication publication(String version, List<Contribution> sources) {
        var merged = PublicationMerger.merge(sources, PublicationMerger.emptyDecisions(), Set.of());
        return new Publication(version, "publication", "digest", null, null, sources.getFirst().receipt(), sources.getFirst().projectionArtifact(),
                merged.snapshot(version, "publication"), sources, PublicationMerger.emptyDecisions(), merged.issueSources(), merged.relationSources());
    }
    private static String registry(String grant, boolean enabled) {
        return """
                {"schemaVersion":"zoop-ingestion-s2-1","revision":"registry-1","sources":[{
                  "sourceId":"source","adapter":"authored-files","inputRoot":"/synthetic","allowedHosts":["example.invalid"],
                  "scopes":[{"scopeId":"body","selection":"synthetic fixture","initialCursor":null,"articleXPath":null,"timestampLimitations":["Synthetic publication dates are fixed test inputs."]}],
                  "grant":{"grantId":"%s","revision":"r1","sourceId":"source","enabled":%s,"rights":"known",
                    "allowedOperations":["read","store","quote-display"],"recipients":[],"purposes":[],"evidence":["synthetic fixture"],"expiresAt":null}}]}
                """.formatted(grant, enabled);
    }
}
