package com.zoop.graph.read;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.json.StrictJson.Obj;
import com.zoop.common.response.Metadata;
import com.zoop.common.response.SectionFailure;
import com.zoop.document.evidence.service.EvidenceService;
import com.zoop.document.repository.DocumentRegistryRepository;
import com.zoop.document.repository.VersionRow;
import com.zoop.graph.importer.MentionIds;
import com.zoop.graph.read.dto.EventDetail;
import com.zoop.graph.read.dto.EventDetail.ArticleOut;
import com.zoop.graph.read.dto.EventDetail.CompanyLink;
import com.zoop.graph.read.dto.EventDetail.FieldDecisionOut;
import com.zoop.graph.read.dto.EventDetail.FieldOutcome;
import com.zoop.graph.read.dto.EventDetail.FollowRef;
import com.zoop.graph.read.dto.EventDetail.Follows;
import com.zoop.graph.read.dto.EventDetail.MentionOut;
import com.zoop.graph.read.dto.EventDetail.Participant;
import com.zoop.graph.read.dto.EventDetail.RelationOut;
import com.zoop.graph.read.dto.EventDetail.SourceSupportOut;
import com.zoop.graph.read.dto.EventDetail.Unavailable;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Article;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Issue;
import com.zoop.graph.snapshot.PublicGraphSnapshot.MentionRef;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Relation;
import java.time.Instant;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;
import java.util.function.Predicate;
import java.util.stream.Collectors;
import org.springframework.stereotype.Service;

/**
 * {@code getEvent} (#64, FS021): one issue of the pinned, filtered public graph with its relations, companies, articles and
 * sequence from the snapshot, and, for an imported version, the original mentions, operator field verdicts and source support
 * the AI handoff carried (the version's receipt, read once). An issue that is not visible in that read is 404, never looked up in
 * another version. Values held or rejected by an operator field verdict never leave this service, and nothing is inferred that
 * the handoff did not give: no summary, no approval, no confirmed role.
 */
@Service
public class EventDetailService {
    static final String SUMMARY_UNAVAILABLE = "사건 요약은 아직 제공되지 않습니다.";
    private static final String IMPORTED = "snapshot";
    private static final Set<String> WITHHELD = Set.of("HOLD", "REJECT");
    /** The only receipt bundle schema whose mentions and field verdicts this service reads. */
    private static final String BUNDLE_SCHEMA = "zoop-graph-handoff-bundle-5";

    private final PublicGraphReader reader;
    private final EvidenceService receipts;
    private final DocumentRegistryRepository registry;

    public EventDetailService(PublicGraphReader reader, EvidenceService receipts, DocumentRegistryRepository registry) {
        this.reader = reader;
        this.receipts = receipts;
        this.registry = registry;
    }

    public EventDetail get(String id, String round, String graphVersion, String asOf, String requestId) {
        Instant at = parseInstant(asOf);
        PublicGraphReader.Pinned pinned = reader.read(round, graphVersion, at);
        DisplayGraph graph = pinned.graph();
        Issue issue = graph.issues.get(id);
        if (issue == null) throw new CustomException(ErrorCode.RESOURCE_NOT_FOUND);
        PublicGraphSnapshot snapshot = graph.snapshot;
        String versionId = pinned.selected().version().id();
        // Synthetic fixtures have no receipt; an imported version must be describable or the read is 503.
        Obj bundle = IMPORTED.equals(pinned.selected().version().kind())
                ? currentBundle(receipts.graphImportBundle(versionId, requestId)) : null;
        Obj handoff = bundle == null ? null : handoffIssue(bundle, id);

        // Evidence the filtered snapshot still shows (asOf, exclusions); for an imported version also readable right now under
        // the evidence gates (article access, source grant, registry), which the snapshot filter never looks at. Asked once per id.
        Map<String, PublicGraphSnapshot.Evidence> inSnapshot = new LinkedHashMap<>();
        snapshot.evidence().forEach(e -> inSnapshot.put(e.evidenceId(), e));
        Map<String, Boolean> judged = new HashMap<>();
        Predicate<String> shown = e -> inSnapshot.containsKey(e) && (bundle == null
                || judged.computeIfAbsent(e, k -> receipts.shownNow(k, versionId, at, requestId)));

        Map<String, Obj> mentionsById = handoff == null ? Map.of() : mentionsById(handoff, issue, shown);
        // Closed like an issue this read does not show when the head values rest on text that is not wholly shown.
        if (bundle != null && !headShown(issue, mentionsById)) throw new CustomException(ErrorCode.RESOURCE_NOT_FOUND);
        Map<String, String> appIds = appIds(mentionsById);
        Map<String, Set<String>> withheld = handoff == null ? Map.of() : withheld(handoff, appIds);

        // A relation needs all its evidence shown, as the snapshot filter requires for evidence it hides; a FOLLOWS relation
        // also needs the other event's head to be showable, or its label and time would leave through follows.
        List<Relation> relations = snapshot.relations().stream()
                .filter(r -> r.source().equals(id) || r.target().equals(id))
                .filter(r -> r.evidenceIds().stream().allMatch(shown))
                .filter(r -> bundle == null || !"FOLLOWS".equals(r.relationType()) || otherHeadShown(graph, bundle, id, r, shown))
                .toList();
        Set<String> own = new HashSet<>(issue.evidenceIds());
        own.addAll(issue.geographyEvidenceIds());
        List<ArticleOut> articles = articles(snapshot,
                own.stream().filter(shown).map(inSnapshot::get).toList(), mentionsById);
        Metadata metadata = new Metadata("public_graph_snapshot", pinned.selected().asOf(), versionId, requestId, true,
                List.of(new SectionFailure("summary", "SUMMARY_NOT_PRODUCED", SUMMARY_UNAVAILABLE, false,
                        pinned.selected().asOf())));
        return new EventDetail(issue.label(), id, issue.eventTime(), issue.timePrecision(), issue.period(),
                mentions(mentionsById, withheld, shown), articles,
                relations.stream().map(EventDetailService::relation).toList(), companies(graph, id, relations),
                sourceSupport(handoff, articles.stream().map(ArticleOut::id).toList()), fieldDecisions(handoff, appIds),
                issue.evidenceIds().stream().filter(shown).toList(),
                follows(graph, id, relations), null, new Unavailable("unavailable", SUMMARY_UNAVAILABLE), metadata);
    }

    /**
     * The handoff issue behind this snapshot issue (same id); its absence means the receipt does not describe the version. Only
     * the current bundle schema carries the mentions and verdicts read here: an older receipt ({@code -1} has no mentions,
     * {@code -2}/{@code -3} no field verdicts) is SOURCE_UNAVAILABLE, never read as empty lists.
     */
    private static Obj handoffIssue(Obj bundle, String issueId) {
        for (Obj candidate : bundle.objects("issues")) {
            if (issueId.equals(candidate.string("id"))) return candidate;
        }
        throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
    }

    /** Only the current bundle schema carries the mentions and verdicts read here (see {@link #handoffIssue}). */
    private static Obj currentBundle(Obj bundle) {
        if (!bundle.has("schemaVersion") || !BUNDLE_SCHEMA.equals(bundle.string("schemaVersion"))) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        }
        return bundle;
    }

    /**
     * Whether the head values (label, time, period) can be shown: they are the representative mention's when an operator chose
     * one (fieldProvenance.selection operator-representative), and every mention's when they all agree (unanimous, no
     * representative), so every one of those mentions must be wholly shown. Never a first mention picked in place of a missing
     * representative.
     */
    private static boolean headShown(Issue issue, Map<String, Obj> shownMentions) {
        List<String> basis = issue.representativeMentionId() != null ? List.of(issue.representativeMentionId())
                : issue.mentions().stream().map(MentionRef::mentionId).toList();
        return !basis.isEmpty() && shownMentions.keySet().containsAll(basis);
    }

    /** The event on the other end of a FOLLOWS relation passes the same head check as a direct read of it. */
    private static boolean otherHeadShown(DisplayGraph graph, Obj bundle, String id, Relation r, Predicate<String> shown) {
        Issue other = graph.issues.get(r.source().equals(id) ? r.target() : r.source());
        return other != null && headShown(other, mentionsById(handoffIssue(bundle, other.issueId()), other, shown));
    }

    /**
     * Receipt mentions keyed by their app id, in handoff order, kept only when the filtered snapshot still references them (an
     * article published after asOf takes its mentions with it) and every one of their evidence is shown now. The handoff does
     * not say which citation supports which field of the original text, so a mention with any citation withdrawn or excluded
     * is left out whole rather than shown on the part that remains.
     */
    private static Map<String, Obj> mentionsById(Obj handoff, Issue issue, Predicate<String> shown) {
        Set<String> visible = issue.mentions().stream().map(MentionRef::mentionId).collect(Collectors.toSet());
        Map<String, Obj> byId = new LinkedHashMap<>();
        for (Obj mention : handoff.objects("mentions")) {
            String appId = MentionIds.of(mention.string("articleId"), mention.string("articleVersion"),
                    mention.string("mentionId"));
            List<String> evidence = mention.strings("evidenceIds");
            if (visible.contains(appId) && !evidence.isEmpty() && evidence.stream().allMatch(shown)) {
                byId.put(appId, mention);
            }
        }
        return byId;
    }

    /** Per app mention id, the fields (eventTime, period) an operator verdict held or rejected. */
    private static Map<String, Set<String>> withheld(Obj handoff, Map<String, String> appIds) {
        Map<String, Set<String>> out = new HashMap<>();
        for (Obj verdict : handoff.objects("fieldVerdicts")) {
            String appId = appIds.get(producerKey(verdict));
            if (appId != null && WITHHELD.contains(verdict.string("decision"))) {
                out.computeIfAbsent(appId, k -> new HashSet<>()).add(verdict.string("field"));
            }
        }
        return out;
    }

    /** Visible mentions by producer identity, which is how a verdict names its mention. */
    private static Map<String, String> appIds(Map<String, Obj> mentionsById) {
        Map<String, String> out = new HashMap<>();
        mentionsById.forEach((appId, mention) -> out.put(producerKey(mention), appId));
        return out;
    }

    /** (documentId, documentVersion, local mentionId): the local id alone repeats across documents. */
    private static String producerKey(Obj node) {
        return node.string("documentId") + "\n" + node.string("documentVersion") + "\n" + node.string("mentionId");
    }

    private static List<MentionOut> mentions(Map<String, Obj> mentionsById, Map<String, Set<String>> withheld,
            Predicate<String> shown) {
        List<MentionOut> out = new ArrayList<>();
        for (Map.Entry<String, Obj> entry : mentionsById.entrySet()) {
            Obj m = entry.getValue();
            Set<String> hidden = withheld.getOrDefault(entry.getKey(), Set.of());
            boolean timeHidden = hidden.contains("eventTime");
            List<Participant> participants = m.objects("participants").stream()
                    .map(p -> new Participant(p.stringOrNull("companyId"), p.string("name"), p.stringOrNull("role"),
                            // The handoff produces no confirmed roles: any role is S2 text (GRAPH_READ_HANDOFF).
                            p.stringOrNull("role") != null))
                    .toList();
            out.add(new MentionOut(m.string("title"), entry.getKey(), m.string("articleId"), m.string("action"),
                    m.stringOrNull("target"), timeHidden ? null : m.stringOrNull("eventTime"),
                    timeHidden ? "unknown" : m.string("timePrecision"),
                    hidden.contains("period") ? null : m.stringOrNull("period"), m.string("assertionStatus"),
                    participants, m.strings("evidenceIds").stream().filter(shown).toList(),
                    m.bool("background")));
        }
        return out;
    }

    /**
     * The articles the issue's readable evidence cites, by exact (article, version): the same article in another version
     * belongs to whatever issue cites that version. Newest first. publisher comes from the stored article version (the handoff
     * carries none). relationType: PROVIDES_BACKGROUND when every visible mention of that article is background, REPORTS
     * otherwise, null without mentions (a synthetic fixture, or an article cited only for geography).
     */
    private List<ArticleOut> articles(PublicGraphSnapshot snapshot, java.util.Collection<PublicGraphSnapshot.Evidence> evidence,
            Map<String, Obj> mentionsById) {
        Set<String> pairs = evidence.stream().map(e -> e.articleId() + "@" + e.articleVersion()).collect(Collectors.toSet());
        return snapshot.articles().stream().filter(a -> pairs.contains(a.articleId() + "@" + a.version()))
                .sorted(Comparator.comparing((Article a) -> DisplayGraph.publishedAt(a.publishedAt()),
                        Comparator.nullsLast(Comparator.reverseOrder())).thenComparing(Article::articleId))
                .map(a -> new ArticleOut(a.title(), a.articleId(),
                        registry.findVersion(a.articleId(), a.version()).map(VersionRow::publisher).orElse(null), a.url(),
                        a.publishedAt(), articleRelation(a, mentionsById)))
                .toList();
    }

    private static String articleRelation(Article article, Map<String, Obj> mentionsById) {
        List<Obj> own = mentionsById.values().stream()
                .filter(m -> m.string("articleId").equals(article.articleId())
                        && m.string("articleVersion").equals(article.version()))
                .toList();
        if (own.isEmpty()) return null;
        return own.stream().allMatch(m -> m.bool("background")) ? "PROVIDES_BACKGROUND" : "REPORTS";
    }

    private static RelationOut relation(Relation r) {
        return new RelationOut(r.relationId(), DisplayGraph.edgeId(r.relationType(), r.source(), r.target()),
                r.relationType(), r.source(), r.target(), r.role(), r.role() != null, r.assertionStatus(), r.evidenceIds());
    }

    /** One link per (company, relation type) from this issue, keeping the first role the snapshot gives. */
    private static List<CompanyLink> companies(DisplayGraph graph, String id, List<Relation> relations) {
        Map<String, CompanyLink> links = new LinkedHashMap<>();
        for (Relation r : relations) {
            if (!r.source().equals(id) || !DisplayGraph.COMPANY_LINKS.contains(r.relationType())) continue;
            PublicGraphSnapshot.Company company = graph.companies.get(r.target());
            if (company == null) continue;
            links.merge(r.target() + "|" + r.relationType(),
                    new CompanyLink(r.target(), company.label(), r.role(), r.role() != null, r.relationType()),
                    (first, next) -> first.role() != null ? first : next);
        }
        return List.copyOf(links.values());
    }

    /**
     * Copied from the handoff issue (AI: copy, never recompute) when every article it counted is still shown. When some are not
     * (current rights withdrew their evidence, or an exclusion hid it), the shown part only: counts that depend on hidden
     * articles become null (unknown), lists keep shown members. A synthetic fixture declares no origins, so every article's
     * lineage is unknown.
     */
    private static SourceSupportOut sourceSupport(Obj handoff, List<String> shownArticleIds) {
        List<String> visible = shownArticleIds.stream().distinct().sorted().toList();
        if (handoff == null) return new SourceSupportOut(visible.size(), null, visible, null, List.of());
        Obj support = handoff.object("sourceSupport");
        List<String> unknown = support.strings("unknownLineageArticles");
        List<List<String>> groups = new ArrayList<>();
        support.array("duplicateGroups").forEach(g -> {
            List<String> members = new ArrayList<>();
            g.forEach(m -> members.add(m.asString()));
            groups.add(members);
        });
        // Lists are always cut to the visible articles, so a hidden id never leaves even if the counts happen to match.
        Set<String> shown = new TreeSet<>(visible);
        List<String> shownUnknown = unknown.stream().filter(shown::contains).toList();
        List<List<String>> shownGroups = groups.stream().map(g -> g.stream().filter(shown::contains).toList())
                .filter(g -> g.size() >= 2).toList();
        boolean nothingHidden = support.count("articleCount") == visible.size() && shownUnknown.size() == unknown.size()
                && shownGroups.equals(groups);
        return nothingHidden
                ? new SourceSupportOut(visible.size(), nullable(support, "knownLineageCount"), shownUnknown,
                        nullable(support, "independentSourceCount"), shownGroups)
                : new SourceSupportOut(visible.size(), null, shownUnknown, null, shownGroups);
    }

    private static Integer nullable(Obj node, String name) {
        return node.isNull(name) ? null : node.count(name);
    }

    /**
     * Operator verdicts per visible mention: field, decision and reason code only. The judged value itself is not repeated here,
     * so a held or rejected value never leaves through this list either.
     */
    private static List<FieldDecisionOut> fieldDecisions(Obj handoff, Map<String, String> appIds) {
        if (handoff == null) return List.of();
        Map<String, List<FieldOutcome>> byMention = new LinkedHashMap<>();
        for (Obj verdict : handoff.objects("fieldVerdicts")) {
            String appId = appIds.get(producerKey(verdict));
            if (appId == null) continue;
            byMention.computeIfAbsent(appId, k -> new ArrayList<>()).add(new FieldOutcome(verdict.string("field"),
                    verdict.string("decision"), verdict.string("reasonCode")));
        }
        return byMention.entrySet().stream().map(e -> new FieldDecisionOut(null, e.getKey(), e.getValue())).toList();
    }

    /** FOLLOWS points from the later issue to the earlier one; only issues visible in this read are listed. */
    private static Follows follows(DisplayGraph graph, String id, List<Relation> relations) {
        List<FollowRef> previous = new ArrayList<>();
        List<FollowRef> next = new ArrayList<>();
        for (Relation r : relations) {
            if (!"FOLLOWS".equals(r.relationType())) continue;
            boolean later = r.source().equals(id);
            Issue other = graph.issues.get(later ? r.target() : r.source());
            if (other == null) continue;
            FollowRef ref = new FollowRef(other.label(), other.issueId(), other.eventTime(), other.timePrecision());
            (later ? previous : next).add(ref);
        }
        return new Follows(previous, next);
    }

    private static Instant parseInstant(String value) {
        if (value == null || value.isBlank()) return null;
        try {
            return Instant.parse(value);
        } catch (DateTimeParseException exception) {
            throw new CustomException(ErrorCode.INVALID_REQUEST, exception);
        }
    }
}
