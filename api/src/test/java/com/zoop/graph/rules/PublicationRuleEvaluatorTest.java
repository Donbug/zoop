package com.zoop.graph.rules;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.zoop.graph.rules.PublicationRuleEvaluator.EnabledRule;
import com.zoop.graph.rules.PublicationRuleEvaluator.Outcome;
import com.zoop.graph.rules.RuleDefinition.AssertionStatus;
import com.zoop.graph.rules.RuleDefinition.SingleSource;
import com.zoop.graph.snapshot.GraphSnapshotCodec;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Article;
import com.zoop.graph.snapshot.PublicGraphSnapshot.ArticleRef;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Basis;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Company;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Evidence;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Issue;
import com.zoop.graph.snapshot.PublicGraphSnapshot.MentionRef;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Relation;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.json.JsonMapper;

/** The rules doc's cases (docs/development/issue-133-publication-rules.md section 5) over synthetic snapshots. */
class PublicationRuleEvaluatorTest {
    private static final ObjectMapper MAPPER = JsonMapper.builder().build();
    private static final EnabledRule SINGLE_SOURCE = new EnabledRule("single-source@1",
            RuleDefinition.parse("{\"kind\":\"single_source\",\"minSources\":2,\"relationTypes\":[\"INVOLVES\",\"STRUCTURALLY_RELATED_TO\"]}"));
    private static final EnabledRule SPECULATIVE = new EnabledRule("speculative-issue@1",
            RuleDefinition.parse("{\"kind\":\"assertion_status\",\"hide\":[\"cancelled\",\"forecast\"]}"));

    // ------------------------------------------------------------------------------------------------ rule 1 -----

    @Test
    void aRelationBackedByOneArticleIsHiddenAndTwoArticlesStay() {
        Fixture f = new Fixture();
        f.issue("iss-a", "occurred", "art-1", "art-2", "art-3");
        f.relation("rel-one", "INVOLVES", "iss-a", "C1", f.evidence("art-1", "v1"));
        f.relation("rel-two", "INVOLVES", "iss-a", "C2", f.evidence("art-1", "v1"), f.evidence("art-2", "v1"));
        // Two versions of one article are one source.
        f.relation("rel-versions", "INVOLVES", "iss-a", "C3", f.evidence("art-3", "v1"), f.evidence("art-3", "v2"));

        Outcome outcome = apply(f, SINGLE_SOURCE);

        assertEquals(Set.of("rel-one", "rel-versions"), outcome.hiddenRelationIds());
        assertEquals(List.of("rel-one", "rel-versions"), outcome.byRule().get("single-source@1").relationIds());
        assertEquals(List.of("rel-two"), relationIds(outcome));
        assertEquals(List.of("iss-a"), issueIds(outcome));
    }

    @Test
    void aStructuralRelationAlsoCountsItsBasisArticlesAndFollowsIsNotARuleOneTarget() {
        Fixture f = new Fixture();
        f.issue("iss-a", "occurred", "art-1", "art-2");
        f.issue("iss-b", "occurred", "art-1");
        f.relation("rel-anchor", "INVOLVES", "iss-a", "C1", f.evidence("art-1", "v1"), f.evidence("art-2", "v1"));
        f.relation("rel-anchor-b", "INVOLVES", "iss-b", "C1", f.evidence("art-1", "v1"), f.evidence("art-2", "v1"));
        f.structural("rel-structural", "iss-a", "C2", List.of(new ArticleRef("art-2", "v1")), f.evidence("art-1", "v1"));
        f.structural("rel-structural-alone", "iss-a", "C3", List.of(new ArticleRef("art-1", "v1")), f.evidence("art-1", "v1"));
        f.relation("rel-follows", "FOLLOWS", "iss-b", "iss-a");

        Outcome outcome = apply(f, SINGLE_SOURCE);

        assertEquals(Set.of("rel-structural-alone"), outcome.hiddenRelationIds(),
                "evidence art-1 plus basis art-2 is two sources; a FOLLOWS without evidence is never counted");
    }

    // ------------------------------------------------------------------------------------------------ rule 2 -----

    @Test
    void aCancelledOrForecastIssueIsHiddenWithEveryRelationOfIt() {
        Fixture f = new Fixture();
        for (String status : List.of("occurred", "announced", "planned", "forecast", "cancelled", "unknown")) {
            f.issue("iss-" + status, status, "art-" + status);
            f.relation("rel-" + status, "INVOLVES", "iss-" + status, "C1", f.evidence("art-" + status, "v1"));
        }
        f.issue("iss-null", null, "art-null");
        f.relation("rel-null", "INVOLVES", "iss-null", "C1", f.evidence("art-null", "v1"));
        f.structural("rel-forecast-structural", "iss-forecast", "C2", List.of(), f.evidence("art-forecast", "v1"));
        f.relation("rel-follows-in", "FOLLOWS", "iss-occurred", "iss-cancelled");
        f.relation("rel-follows-out", "FOLLOWS", "iss-forecast", "iss-planned");
        f.relation("rel-follows-kept", "FOLLOWS", "iss-occurred", "iss-planned");

        Outcome outcome = apply(f, SPECULATIVE);

        assertEquals(List.of("iss-forecast", "iss-cancelled"), outcome.byRule().get("speculative-issue@1").issueIds());
        assertEquals(Set.of("iss-forecast", "iss-cancelled"), outcome.hiddenIssueIds());
        assertEquals(Set.of("rel-forecast", "rel-cancelled", "rel-forecast-structural", "rel-follows-in", "rel-follows-out"),
                outcome.hiddenRelationIds());
        assertEquals(List.of("iss-occurred", "iss-announced", "iss-planned", "iss-unknown", "iss-null"), issueIds(outcome));
    }

    // ------------------------------------------------------------------------------------------------ cascade -----

    @Test
    void anIssueLeftWithoutCompanyRelationsIsHiddenAndWhatNothingCitesIsDropped() {
        Fixture f = new Fixture();
        f.issue("iss-orphaned", "occurred", "art-1");
        f.relation("rel-only", "INVOLVES", "iss-orphaned", "C1", f.evidence("art-1", "v1"));
        f.issue("iss-kept", "occurred", "art-2", "art-3");
        f.relation("rel-kept", "INVOLVES", "iss-kept", "C1", f.evidence("art-2", "v1"), f.evidence("art-3", "v1"));
        f.relation("rel-follows", "FOLLOWS", "iss-kept", "iss-orphaned");
        // An issue that never had a company relation is not the cascade's to hide.
        f.issue("iss-unlinked", "occurred", "art-4");

        Outcome outcome = apply(f, SINGLE_SOURCE);

        assertEquals(Set.of("iss-orphaned"), outcome.hiddenIssueIds());
        assertEquals(Set.of("rel-only", "rel-follows"), outcome.hiddenRelationIds());
        assertEquals(List.of("iss-kept", "iss-unlinked"), issueIds(outcome));
        assertTrue(outcome.snapshot().articles().stream().noneMatch(a -> a.articleId().equals("art-1")),
                "the hidden issue's only article is dropped");
        assertTrue(outcome.snapshot().evidence().stream().noneMatch(e -> e.articleId().equals("art-1")));
        assertEquals(f.companies, outcome.snapshot().companies(), "companies are the catalogue and always stay");
        readable(outcome);
    }

    @Test
    void bothRulesTogetherRunInTheFixedOrder() {
        Fixture f = new Fixture();
        f.issue("iss-forecast", "forecast", "art-1", "art-2");
        f.relation("rel-forecast", "INVOLVES", "iss-forecast", "C1", f.evidence("art-1", "v1"), f.evidence("art-2", "v1"));
        f.issue("iss-single", "occurred", "art-3");
        f.relation("rel-single", "INVOLVES", "iss-single", "C1", f.evidence("art-3", "v1"));

        Outcome outcome = apply(f, SINGLE_SOURCE, SPECULATIVE);

        assertEquals(List.of(), outcome.byRule().get("single-source@1").relationIds().stream()
                .filter("rel-forecast"::equals).toList(), "a relation already hidden with its issue is not a rule 1 hit");
        assertEquals(Set.of("iss-forecast", "iss-single"), outcome.hiddenIssueIds());
        assertEquals(List.of(), issueIds(outcome));
        readable(outcome);
    }

    // ------------------------------------------------------------------------------------------------ hide-only -----

    @Test
    void withoutRulesTheSnapshotIsUnchangedAndWithRulesItIsAReadableSubset() throws Exception {
        for (String version : List.of("fixture-2026-10-01", "fixture-2026-10-08")) {
            PublicGraphSnapshot input = fixture(version);
            assertEquals(input, PublicationRuleEvaluator.apply(input, List.of()).snapshot(), version);

            EnabledRule everything = new EnabledRule("hide-all@1", new AssertionStatus(RuleDefinition.ASSERTION_STATUSES));
            EnabledRule strict = new EnabledRule("strict@1", new SingleSource(100, RuleDefinition.COMPANY_RELATIONS));
            for (List<EnabledRule> rules : List.of(List.of(SINGLE_SOURCE), List.of(SPECULATIVE), List.of(strict),
                    List.of(everything), List.of(SINGLE_SOURCE, SPECULATIVE, strict))) {
                Outcome outcome = PublicationRuleEvaluator.apply(input, rules);
                PublicGraphSnapshot output = outcome.snapshot();
                assertTrue(input.issues().containsAll(output.issues()), version);
                assertTrue(input.relations().containsAll(output.relations()), version);
                assertTrue(input.articles().containsAll(output.articles()), version);
                assertTrue(input.evidence().containsAll(output.evidence()), version);
                assertEquals(input.companies(), output.companies());
                readable(outcome);
            }
        }
    }

    @Test
    void theSameInputGivesTheSameBytesWhateverTheRuleOrder() throws Exception {
        PublicGraphSnapshot input = fixture("fixture-2026-10-08");
        Outcome first = PublicationRuleEvaluator.apply(input, List.of(SINGLE_SOURCE, SPECULATIVE));
        Outcome again = PublicationRuleEvaluator.apply(input, List.of(SPECULATIVE, SINGLE_SOURCE));

        assertArrayEquals(MAPPER.writeValueAsBytes(first.snapshot()), MAPPER.writeValueAsBytes(again.snapshot()));
        assertArrayEquals(MAPPER.writeValueAsBytes(first.byRule()), MAPPER.writeValueAsBytes(again.byRule()));
        assertEquals(first.hiddenRelationIds().stream().sorted().toList(), List.copyOf(again.hiddenRelationIds()),
                "the hidden ids are in id order, not a per-JVM hash order");
        assertEquals(first.hiddenIssueIds().stream().sorted().toList(), List.copyOf(again.hiddenIssueIds()));
        assertEquals(List.of("single-source@1", "speculative-issue@1"), List.copyOf(again.byRule().keySet()),
                "byRule is in rule id order");
    }

    @Test
    void aHiddenRelationsEvidenceStaysWhenTheVisibleIssueCitesItItself() {
        Fixture f = new Fixture();
        f.issue("iss-a", "occurred", "art-1", "art-2");
        String issueOwn = f.issue("iss-a").evidenceIds().get(0);
        f.relation("rel-single", "INVOLVES", "iss-a", "C1", issueOwn);
        f.relation("rel-kept", "INVOLVES", "iss-a", "C2", f.evidence("art-1", "v1"), f.evidence("art-2", "v1"));

        Outcome outcome = apply(f, SINGLE_SOURCE);

        assertEquals(Set.of("rel-single"), outcome.hiddenRelationIds());
        assertTrue(outcome.snapshot().evidence().stream().anyMatch(e -> e.evidenceId().equals(issueOwn)),
                "hiding the relation hides the claim, not the issue's own citation");
        readable(outcome);
    }

    @Test
    void basisAndImpactOnlyCitationsStayWhileTheirRelationIsVisible() {
        // Spans nothing lists directly: one in the structural basis article art-9, one beside the INVOLVES citation in art-5.
        // The evidence read finds them by article version and proves them against the receipt, so they are not orphans.
        Fixture f = new Fixture();
        f.issue("iss-a", "occurred", "art-1", "art-2");
        f.structural("rel-structural", "iss-a", "C2", List.of(new ArticleRef("art-9", "v1")), f.evidence("art-1", "v1"));
        String basisOnly = f.evidence("art-9", "v1");
        f.relation("rel-involves", "INVOLVES", "iss-a", "C1", f.evidence("art-5", "v1"), f.evidence("art-1", "v1"));
        String impactOnly = f.evidence("art-5", "v1");
        PublicGraphSnapshot input = f.snapshot();

        assertEquals(input, PublicationRuleEvaluator.apply(input, List.of()).snapshot(), "no rules: the input");
        for (EnabledRule unmatched : List.of(SINGLE_SOURCE, SPECULATIVE)) {
            Outcome outcome = PublicationRuleEvaluator.apply(input, List.of(unmatched));
            assertEquals(input, outcome.snapshot(), unmatched.ruleId() + " matches nothing: the input");
        }

        EnabledRule strictStructural = new EnabledRule("strict-structural@1",
                new SingleSource(3, Set.of("STRUCTURALLY_RELATED_TO")));
        Outcome noBasis = PublicationRuleEvaluator.apply(input, List.of(strictStructural));
        assertEquals(Set.of("rel-structural"), noBasis.hiddenRelationIds());
        assertEquals(Set.of(impactOnly), indirect(noBasis, basisOnly, impactOnly), "the last basis citing art-9 is gone");
        assertTrue(noBasis.snapshot().articles().stream().noneMatch(a -> a.articleId().equals("art-9")));
        readable(noBasis);

        EnabledRule strictInvolves = new EnabledRule("strict-involves@1", new SingleSource(3, Set.of("INVOLVES")));
        Outcome noImpact = PublicationRuleEvaluator.apply(input, List.of(strictInvolves));
        assertEquals(Set.of("rel-involves"), noImpact.hiddenRelationIds());
        assertEquals(Set.of(basisOnly), indirect(noImpact, basisOnly, impactOnly), "the last INVOLVES citing art-5 is gone");
        assertTrue(noImpact.snapshot().articles().stream().noneMatch(a -> a.articleId().equals("art-5")));
        readable(noImpact);

        for (Outcome outcome : List.of(noBasis, noImpact)) {
            assertTrue(outcome.snapshot().relations().stream()
                    .noneMatch(r -> r.evidenceIds().contains(basisOnly) || r.evidenceIds().contains(impactOnly)),
                    "an indirect citation is never added to a relation's evidenceIds");
        }
    }

    @Test
    void ruleIdsAreUniqueAndAnUnreadableDefinitionNeverEvaluates() {
        for (String id : List.of("single-source", "@1", "single-source@0", "1rule@1", "single source@1")) {
            assertThrows(IllegalArgumentException.class, () -> new EnabledRule(id, SINGLE_SOURCE.definition()), id);
        }
        assertThrows(IllegalArgumentException.class, () -> PublicationRuleEvaluator.apply(new Fixture().snapshot(),
                List.of(SINGLE_SOURCE, new EnabledRule("single-source@1", SPECULATIVE.definition()))));
        for (String json : List.of(
                "{\"kind\":\"regex\",\"pattern\":\".*\"}",
                "{\"kind\":\"single_source\",\"minSources\":2}",
                "{\"kind\":\"single_source\",\"minSources\":2,\"relationTypes\":[\"INVOLVES\"],\"extra\":1}",
                "{\"kind\":\"single_source\",\"minSources\":1,\"relationTypes\":[\"INVOLVES\"]}",
                "{\"kind\":\"single_source\",\"minSources\":\"2\",\"relationTypes\":[\"INVOLVES\"]}",
                "{\"kind\":\"single_source\",\"minSources\":2,\"relationTypes\":[\"FOLLOWS\"]}",
                "{\"kind\":\"single_source\",\"minSources\":2,\"relationTypes\":[]}",
                "{\"kind\":\"single_source\",\"minSources\":2,\"relationTypes\":[\"INVOLVES\",\"INVOLVES\"]}",
                "{\"kind\":\"assertion_status\",\"hide\":[\"rumoured\"]}",
                "{\"kind\":\"assertion_status\",\"hide\":[]}",
                "{\"hide\":[\"cancelled\"]}",
                "[\"cancelled\"]",
                "not json")) {
            assertThrows(InvalidRuleDefinitionException.class, () -> RuleDefinition.parse(json), json);
        }
        assertEquals(new SingleSource(3, Set.of("INVOLVES")),
                RuleDefinition.parse("{\"minSources\":3,\"relationTypes\":[\"INVOLVES\"],\"kind\":\"single_source\"}"));
    }

    // ------------------------------------------------------------------------------------------------ helpers -----

    private static Outcome apply(Fixture f, EnabledRule... rules) {
        return PublicationRuleEvaluator.apply(f.snapshot(), List.of(rules));
    }

    private static List<String> issueIds(Outcome outcome) {
        return outcome.snapshot().issues().stream().map(Issue::issueId).toList();
    }

    private static List<String> relationIds(Outcome outcome) {
        return outcome.snapshot().relations().stream().map(Relation::relationId).toList();
    }

    /** Which of the given evidence ids the output kept. */
    private static Set<String> indirect(Outcome outcome, String... evidenceIds) {
        Set<String> wanted = Set.of(evidenceIds);
        return outcome.snapshot().evidence().stream().map(Evidence::evidenceId).filter(wanted::contains)
                .collect(Collectors.toSet());
    }

    /** The output is a snapshot the app can store and read back: every reference still closes. */
    private static void readable(Outcome outcome) {
        PublicGraphSnapshot snapshot = outcome.snapshot();
        GraphSnapshotCodec.read(MAPPER.writeValueAsBytes(snapshot), snapshot.versionId());
    }

    private static PublicGraphSnapshot fixture(String version) throws Exception {
        try (InputStream in = PublicationRuleEvaluatorTest.class.getResourceAsStream("/graph-fixtures/" + version + ".json")) {
            return GraphSnapshotCodec.read(in.readAllBytes(), version);
        }
    }

    /** A synthetic snapshot: each issue cites its own articles, every relation cites the evidence it is given. */
    private static final class Fixture {
        final List<Company> companies = List.of(new Company("C1", "회사 1", null, null), new Company("C2", "회사 2", null, null),
                new Company("C3", "회사 3", null, null));
        private final List<Issue> issues = new ArrayList<>();
        private final List<Relation> relations = new ArrayList<>();
        private final List<Article> articles = new ArrayList<>();
        private final List<Evidence> evidence = new ArrayList<>();

        void issue(String id, String assertionStatus, String... articleIds) {
            List<String> evidenceIds = new ArrayList<>();
            List<MentionRef> mentions = new ArrayList<>();
            for (String articleId : articleIds) {
                evidenceIds.add(evidence(articleId, "v1"));
                mentions.add(new MentionRef("men-" + id + "-" + articleId, articleId, "v1"));
            }
            issues.add(new Issue(id, "이슈 " + id, "2026-09-22", "day", null, assertionStatus, null, null, "domestic", "geo-1",
                    List.of(evidenceIds.get(0)), List.of(articleIds), evidenceIds, mentions, mentions.get(0).mentionId(),
                    "2026-09-22"));
        }

        Issue issue(String id) {
            return issues.stream().filter(i -> i.issueId().equals(id)).findFirst().orElseThrow();
        }

        void relation(String id, String type, String source, String target, String... evidenceIds) {
            relations.add(new Relation(id, type, source, target, null, null, List.of(evidenceIds), List.of()));
        }

        void structural(String id, String source, String target, List<ArticleRef> basisArticles, String... evidenceIds) {
            for (ArticleRef article : basisArticles) {
                version(article.articleId(), article.articleVersion());
            }
            relations.add(new Relation(id, "STRUCTURALLY_RELATED_TO", source, target, null, null, List.of(evidenceIds),
                    List.of(new Basis("basis-" + id, "SUPPLIES", "2026-09-29T00:00:00Z", null, null, List.of("KR"),
                            basisArticles))));
        }

        /** A new evidence span in that article version (created with the version when missing). */
        String evidence(String articleId, String version) {
            version(articleId, version);
            String id = "ev-" + (evidence.size() + 1);
            evidence.add(new Evidence(id, articleId, version, 0, 10));
            return id;
        }

        private void version(String articleId, String version) {
            if (articles.stream().noneMatch(a -> a.articleId().equals(articleId) && a.version().equals(version))) {
                articles.add(new Article(articleId, version, "기사 " + articleId, "https://example.invalid/" + articleId,
                        "2026-09-22"));
            }
        }

        PublicGraphSnapshot snapshot() {
            return new PublicGraphSnapshot(PublicGraphSnapshot.FORMAT, "gv-test", null, companies, issues, relations, articles,
                    evidence);
        }
    }
}
