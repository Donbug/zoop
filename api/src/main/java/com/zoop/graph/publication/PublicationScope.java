package com.zoop.graph.publication;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

import com.zoop.graph.publication.GraphPublicationReader.IssueRef;
import com.zoop.graph.publication.GraphPublicationReader.RelationRef;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Issue;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Relation;

/**
 * What a member exclusion or an issue retirement ({@link PublicationMerger#DECISIONS_SCHEMA_3}) removes from a composition:
 * the relation records whose endpoint left, and the articles and evidence nothing public cites any more.
 */
public final class PublicationScope {
    private PublicationScope() {}

    /**
     * The relation records a decision removed: a record whose issue endpoint (the source, and the target of {@code FOLLOWS}) is an
     * excluded member or belongs to a retired public issue. A record of an excluded source whose endpoint is another, valid member stays.
     */
    static Set<RelationRef> dropped(Map<RelationRef, Relation> relations, PublicationMerger.Effective effective) {
        Set<RelationRef> dropped = new HashSet<>();
        if (effective.excludedMembers().isEmpty() && effective.retiredIssues().isEmpty()) return dropped;
        relations.forEach((ref, relation) -> { if (gone(ref, relation, effective)) dropped.add(ref); });
        return dropped;
    }

    /** True when a relation record's issue endpoint (the source, and the target of {@code FOLLOWS}) is an original a decision in force removed. */
    public static boolean gone(RelationRef ref, Relation relation, PublicationMerger.Effective effective) {
        boolean gone = effective.voided(new IssueRef(ref.sourceVersionId(), relation.source()));
        if ("FOLLOWS".equals(relation.relationType())) gone |= effective.voided(new IssueRef(ref.sourceVersionId(), relation.target()));
        return gone;
    }

    record Cleaned(List<PublicGraphSnapshot.Article> articles, List<PublicGraphSnapshot.Evidence> evidence) {}

    /**
     * The union's articles and evidence without what only removed members and records cited. Only a citation a decision removed is
     * dropped (evidence by id; an article by the exact version a mention, a basis article or removed evidence named), and only while
     * nothing kept (an issue's articles, evidence, geography evidence and mentions; a relation's evidence and basis articles; the
     * article of evidence that stays) cites it, so shared proof survives and a stored publication that carries neither decision is
     * reproduced byte for byte.
     */
    static Cleaned clean(List<PublicGraphSnapshot.Article> articles, List<PublicGraphSnapshot.Evidence> evidence, List<Issue> issues,
            List<Relation> relations, Set<IssueRef> droppedMembers, Set<RelationRef> droppedRelations,
            Map<IssueRef, Issue> originals, Map<RelationRef, Relation> originalRelations) {
        if (droppedMembers.isEmpty() && droppedRelations.isEmpty()) return new Cleaned(articles, evidence);
        Set<String> droppedEvidence = new HashSet<>(), droppedArticles = new HashSet<>();
        for (IssueRef ref : droppedMembers) {
            Issue issue = originals.get(ref);
            droppedEvidence.addAll(issue.evidenceIds()); droppedEvidence.addAll(issue.geographyEvidenceIds());
            issue.mentions().forEach(m -> droppedArticles.add(key(m.articleId(), m.articleVersion())));
        }
        for (RelationRef ref : droppedRelations) {
            Relation relation = originalRelations.get(ref);
            droppedEvidence.addAll(relation.evidenceIds());
            relation.basis().forEach(b -> b.articles().forEach(a -> droppedArticles.add(key(a.articleId(), a.articleVersion()))));
        }
        // A removed citation names an article version through a mention, a basis article or the article of removed evidence; an
        // issue's id-only article list names no version, so a version nothing removed cited is not a decision's target and stays.
        for (var e : evidence) if (droppedEvidence.contains(e.evidenceId())) droppedArticles.add(key(e.articleId(), e.articleVersion()));
        Set<String> liveEvidence = new HashSet<>(), liveArticleIds = new HashSet<>(), liveArticles = new HashSet<>();
        for (Issue issue : issues) {
            liveArticleIds.addAll(issue.articleIds()); liveEvidence.addAll(issue.evidenceIds()); liveEvidence.addAll(issue.geographyEvidenceIds());
            issue.mentions().forEach(m -> liveArticles.add(key(m.articleId(), m.articleVersion())));
        }
        for (Relation relation : relations) {
            liveEvidence.addAll(relation.evidenceIds());
            relation.basis().forEach(b -> b.articles().forEach(a -> liveArticles.add(key(a.articleId(), a.articleVersion()))));
        }
        List<PublicGraphSnapshot.Evidence> keptEvidence = new ArrayList<>();
        for (var e : evidence) {
            if (droppedEvidence.contains(e.evidenceId()) && !liveEvidence.contains(e.evidenceId())) continue;
            keptEvidence.add(e); liveArticles.add(key(e.articleId(), e.articleVersion()));
        }
        List<PublicGraphSnapshot.Article> keptArticles = new ArrayList<>();
        for (var a : articles) {
            String key = key(a.articleId(), a.version());
            if (droppedArticles.contains(key) && !liveArticleIds.contains(a.articleId()) && !liveArticles.contains(key)) continue;
            keptArticles.add(a);
        }
        return new Cleaned(List.copyOf(keptArticles), List.copyOf(keptEvidence));
    }

    private static String key(String articleId, String version) { return articleId + "\n" + version; }
}
