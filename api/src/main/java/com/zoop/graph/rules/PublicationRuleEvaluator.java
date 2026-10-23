package com.zoop.graph.rules;

import com.zoop.graph.rules.RuleDefinition.AssertionStatus;
import com.zoop.graph.rules.RuleDefinition.SingleSource;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Article;
import com.zoop.graph.snapshot.PublicGraphSnapshot.ArticleRef;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Basis;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Evidence;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Issue;
import com.zoop.graph.snapshot.PublicGraphSnapshot.MentionRef;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Relation;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.TreeSet;
import java.util.regex.Pattern;

/**
 * The one function every use of the publication rules shares (rules doc 2-4): import filtering, reapplying the current rules to
 * a receipt, and the per-rule statistics. Its input is a publication-eligible snapshot and its output a subset of it, so a rule can
 * only keep content off the public graph: it never adds an issue, a relation or a HOLD, and never changes a value (AI owner
 * 2026-10-22, 5-A). Companies are the catalogue and always stay.
 *
 * <p>Hiding runs in a fixed order (rules doc 2-5):
 * <ol>
 * <li>issue rules hide issues;</li>
 * <li>every relation of a hidden issue is hidden;</li>
 * <li>relation rules hide relations that are left;</li>
 * <li>an issue that had company relations ({@code INVOLVES}, {@code STRUCTURALLY_RELATED_TO}) and has none left is hidden;</li>
 * <li>a {@code FOLLOWS} with a hidden end is hidden;</li>
 * <li>evidence and article versions no visible issue or relation cites are dropped.</li>
 * </ol>
 * One pass is enough: {@code FOLLOWS} never counts as a company relation, so step 5 cannot hide another issue. An issue that
 * never had a company relation is not hidden by step 4, so with no rules the output is the input.
 *
 * <p>Hiding a relation hides its claim (the issue-company edge), not the article text: evidence a visible issue cites itself
 * ({@code evidenceIds}, {@code geographyEvidenceIds}) stays with the issue even when a hidden relation cited it too.
 */
public final class PublicationRuleEvaluator {
    private PublicationRuleEvaluator() {
    }

    /**
     * What applying the rules left public, and what each rule's own condition matched (before the cascade). The hidden id sets
     * iterate in id order and {@code byRule} in rule id order, so anything written from them is the same bytes for the same input.
     */
    public record Outcome(PublicGraphSnapshot snapshot, Set<String> hiddenIssueIds, Set<String> hiddenRelationIds,
            Map<String, Hits> byRule) {
        public Outcome {
            hiddenIssueIds = Collections.unmodifiableSortedSet(new TreeSet<>(hiddenIssueIds));
            hiddenRelationIds = Collections.unmodifiableSortedSet(new TreeSet<>(hiddenRelationIds));
            byRule = Collections.unmodifiableMap(new TreeMap<>(byRule));
        }
    }

    /** Ids a rule's condition matched, in snapshot order. */
    public record Hits(List<String> issueIds, List<String> relationIds) {
        public Hits {
            issueIds = List.copyOf(issueIds);
            relationIds = List.copyOf(relationIds);
        }
    }

    /**
     * A publication rule id, {@code <ruleId>@<version>}. The same rule as the table's {@code ck_publication_rules_id} CHECK
     * ({@code V20261023120000__create_publication_rules.sql}); a change to one must change the other.
     */
    public static final Pattern RULE_ID = Pattern.compile("[A-Za-z][A-Za-z0-9_-]{0,63}@[1-9][0-9]{0,8}");

    /** One enabled rule: its versioned id ({@link #RULE_ID}, as {@code publication_rules.id}) and parsed definition. */
    public record EnabledRule(String ruleId, RuleDefinition definition) {
        public EnabledRule {
            if (ruleId == null || !RULE_ID.matcher(ruleId).matches() || definition == null) {
                throw new IllegalArgumentException("rule");
            }
        }
    }

    public static Outcome apply(PublicGraphSnapshot snapshot, List<EnabledRule> rules) {
        Set<String> ruleIds = new HashSet<>();
        for (EnabledRule rule : rules) {
            if (!ruleIds.add(rule.ruleId())) throw new IllegalArgumentException("duplicate rule " + rule.ruleId());
        }
        Map<String, Hits> byRule = new LinkedHashMap<>();

        // 1. Issue rules.
        Set<String> hiddenIssues = new LinkedHashSet<>();
        for (EnabledRule rule : rules) {
            if (rule.definition() instanceof AssertionStatus status) {
                List<String> hits = new ArrayList<>();
                for (Issue issue : snapshot.issues()) {
                    if (issue.assertionStatus() != null && status.hide().contains(issue.assertionStatus())) {
                        hits.add(issue.issueId());
                    }
                }
                hiddenIssues.addAll(hits);
                byRule.put(rule.ruleId(), new Hits(hits, List.of()));
            }
        }

        // 2. The relations of hidden issues.
        Set<String> hiddenRelations = new LinkedHashSet<>();
        for (Relation relation : snapshot.relations()) {
            if (touches(relation, hiddenIssues)) hiddenRelations.add(relation.relationId());
        }

        // 3. Relation rules, on what is left.
        Map<String, String> articleOf = new HashMap<>();
        for (Evidence evidence : snapshot.evidence()) {
            articleOf.put(evidence.evidenceId(), evidence.articleId());
        }
        for (EnabledRule rule : rules) {
            if (rule.definition() instanceof SingleSource single) {
                List<String> hits = new ArrayList<>();
                for (Relation relation : snapshot.relations()) {
                    if (!hiddenRelations.contains(relation.relationId()) && single.relationTypes().contains(relation.relationType())
                            && sourceArticles(relation, articleOf).size() < single.minSources()) {
                        hits.add(relation.relationId());
                    }
                }
                byRule.put(rule.ruleId(), new Hits(List.of(), hits));
            }
        }
        byRule.values().forEach(hits -> hiddenRelations.addAll(hits.relationIds()));

        // 4. Issues whose company relations are all hidden now.
        Set<String> linked = new HashSet<>();
        Set<String> stillLinked = new HashSet<>();
        for (Relation relation : snapshot.relations()) {
            if (RuleDefinition.COMPANY_RELATIONS.contains(relation.relationType())) {
                linked.add(relation.source());
                if (!hiddenRelations.contains(relation.relationId())) stillLinked.add(relation.source());
            }
        }
        for (Issue issue : snapshot.issues()) {
            if (linked.contains(issue.issueId()) && !stillLinked.contains(issue.issueId())) hiddenIssues.add(issue.issueId());
        }

        // 5. FOLLOWS (and anything else) touching a hidden issue.
        for (Relation relation : snapshot.relations()) {
            if (touches(relation, hiddenIssues)) hiddenRelations.add(relation.relationId());
        }

        // 6. What the visible issues and relations still cite.
        List<Issue> issues = snapshot.issues().stream().filter(i -> !hiddenIssues.contains(i.issueId())).toList();
        List<Relation> relations = snapshot.relations().stream()
                .filter(r -> !hiddenRelations.contains(r.relationId())).toList();
        Set<String> citedEvidence = new HashSet<>();
        Set<String> citedArticleIds = new HashSet<>();
        Set<String> citedVersions = new HashSet<>();
        for (Issue issue : issues) {
            citedEvidence.addAll(issue.evidenceIds());
            citedEvidence.addAll(issue.geographyEvidenceIds());
            citedArticleIds.addAll(issue.articleIds());
            for (MentionRef mention : issue.mentions()) {
                citedVersions.add(key(mention.articleId(), mention.articleVersion()));
            }
        }
        for (Relation relation : relations) {
            citedEvidence.addAll(relation.evidenceIds());
            for (Basis basis : relation.basis()) {
                for (ArticleRef article : basis.articles()) {
                    citedVersions.add(key(article.articleId(), article.articleVersion()));
                }
            }
        }
        List<Evidence> evidence = snapshot.evidence().stream().filter(e -> citedEvidence.contains(e.evidenceId())).toList();
        for (Evidence e : evidence) {
            citedVersions.add(key(e.articleId(), e.articleVersion()));
        }
        // An issue's articleIds name articles, not versions: every version of a named article stays, as the snapshot requires.
        List<Article> articles = snapshot.articles().stream()
                .filter(a -> citedArticleIds.contains(a.articleId()) || citedVersions.contains(key(a.articleId(), a.version())))
                .toList();

        PublicGraphSnapshot visible = new PublicGraphSnapshot(snapshot.snapshotFormat(), snapshot.versionId(),
                snapshot.sourceBundleId(), snapshot.companies(), issues, relations, articles, evidence);
        return new Outcome(visible, hiddenIssues, hiddenRelations, byRule);
    }

    /**
     * The distinct articles behind a relation (rules doc, rule 1): the articles of its evidence and, for a structural relation, of
     * its basis source articles. Versions of one article count once.
     */
    static Set<String> sourceArticles(Relation relation, Map<String, String> articleOf) {
        Set<String> articles = new HashSet<>();
        for (String evidenceId : relation.evidenceIds()) {
            String articleId = articleOf.get(evidenceId);
            if (articleId != null) articles.add(articleId);
        }
        if ("STRUCTURALLY_RELATED_TO".equals(relation.relationType())) {
            for (Basis basis : relation.basis()) {
                for (ArticleRef article : basis.articles()) {
                    articles.add(article.articleId());
                }
            }
        }
        return articles;
    }

    private static boolean touches(Relation relation, Set<String> hiddenIssues) {
        return hiddenIssues.contains(relation.source())
                || "FOLLOWS".equals(relation.relationType()) && hiddenIssues.contains(relation.target());
    }

    private static String key(String articleId, String version) {
        return articleId + "@" + version;
    }
}
