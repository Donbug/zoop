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
import com.zoop.graph.importer.LegacyRealPackage;
import com.zoop.graph.publication.GraphPublicationReader.Contribution;
import com.zoop.graph.publication.GraphPublicationReader.IssueRef;
import com.zoop.graph.publication.GraphPublicationReader.Publication;
import com.zoop.graph.read.dto.EventDetail;
import com.zoop.graph.read.dto.EventDetail.ApprovalOut;
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
 * sequence from the snapshot. Original contribution receipts retain source-local mentions and field verdicts; exact
 * field owners supply the headline proof. Current rights apply before the detail is projected. Mixed approval provenance
 * remains nullable, and multi-source support is recomputed from declared origins and exact text hashes.
 */
@Service
public class EventDetailService {
    static final String SUMMARY_UNAVAILABLE = "사건 요약은 아직 제공되지 않습니다.";
    private static final String IMPORTED = "snapshot";
    private static final Set<String> WITHHELD = Set.of("HOLD", "REJECT");
    /** INVOLVES provenance when at least one contributing S3 relation rests on an operator's final approval of a HOLD. */
    private static final String OPERATOR_APPROVED = "manual-operator-final-approval";
    static final ApprovalOut ADMIN_APPROVAL = new ApprovalOut("admin-review", "관리자 승인", "relation", null);
    /** Immutable receipt formats with the same mention, field-verdict, source-support and headline-selection contract. */
    private static final Set<String> BUNDLE_SCHEMAS = Set.of(
            "zoop-graph-handoff-bundle-5", "zoop-graph-handoff-bundle-6", "zoop-graph-handoff-bundle-7",
            "zoop-graph-handoff-bundle-8", "zoop-graph-handoff-bundle-9",
            LegacyRealPackage.BUNDLE_SCHEMA, LegacyRealPackage.METADATA_BUNDLE_SCHEMA);

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
        PublicGraphReader.Pinned pinned = reader.read(round, graphVersion, at, requestId);
        DisplayGraph graph = pinned.graph();
        Issue issue = graph.issues.get(id);
        if (issue == null) throw new CustomException(ErrorCode.RESOURCE_NOT_FOUND);
        PublicGraphSnapshot snapshot = graph.snapshot;
        String versionId = pinned.selected().version().id();
        // Synthetic fixtures have no receipt; an imported version must be describable or the read is 503.
        Publication publication = IMPORTED.equals(pinned.selected().version().kind())
                ? receipts.graphPublication(versionId, requestId) : null;

        // The shared overlay filters the snapshot first; citation reads also validate the exact retained evidence proof.
        Map<String, PublicGraphSnapshot.Evidence> inSnapshot = new LinkedHashMap<>();
        snapshot.evidence().forEach(e -> inSnapshot.put(e.evidenceId(), e));
        Map<String, Boolean> judged = new HashMap<>();
        Instant filteredAt = pinned.selected().asOfRequested() ? pinned.selected().asOf() : null;
        Predicate<String> shown = e -> inSnapshot.containsKey(e) && (publication == null
                || judged.computeIfAbsent(e, k -> (round == null ? receipts.shownNow(k, versionId, filteredAt, requestId)
                        : receipts.shownNow(k, round, versionId, at, requestId))));

        List<SourceIssue> sources = publication == null ? List.of() : sourceIssues(publication, issue, shown);
        if (publication != null && !readable(publication, issue, shown))
            throw new CustomException(ErrorCode.RESOURCE_NOT_FOUND);
        List<Obj> visibleMentions = sources.stream().flatMap(s -> s.mentions().values().stream()).toList();

        // A relation needs all its evidence shown, as the snapshot filter requires for evidence it hides; a FOLLOWS relation
        // also needs the other event's head to be showable, or its label and time would leave through follows.
        List<Relation> relations = snapshot.relations().stream()
                .filter(r -> r.source().equals(id) || r.target().equals(id))
                .filter(r -> r.evidenceIds().stream().allMatch(shown))
                .filter(r -> publication == null || !"FOLLOWS".equals(r.relationType())
                        || otherHeadShown(graph, publication, id, r, shown))
                .toList();
        Set<String> own = new HashSet<>(issue.evidenceIds());
        own.addAll(issue.geographyEvidenceIds());
        List<ArticleOut> articles = articles(snapshot,
                own.stream().filter(shown).map(inSnapshot::get).toList(), visibleMentions);
        Metadata metadata = new Metadata(pinned.selected().source(), pinned.selected().asOf(), versionId, requestId, true,
                List.of(new SectionFailure("summary", "SUMMARY_NOT_PRODUCED", SUMMARY_UNAVAILABLE, false,
                        pinned.selected().asOf())));
        Map<String, Boolean> roleFlags = legacyRelationRoleFlags(publication, relations);
        return new EventDetail(issue.label(), id, issue.eventTime(), issue.timePrecision(), issue.period(),
                sources.stream().flatMap(s -> mentions(s.mentions(),
                        withheld(s.issue(), appIds(s.mentions()), s.source().bundle().string("schemaVersion")), shown).stream())
                        .distinct().toList(), articles,
                relations.stream().map(r -> relation(r, roleFlags.getOrDefault(r.relationId(), r.role() != null))).toList(),
                companies(graph, id, relations, roleFlags),
                sourceSupport(publication, sources, snapshot, own.stream().filter(shown).map(inSnapshot::get).toList()),
                sources.stream().flatMap(s -> fieldDecisions(s.issue(), appIds(s.mentions())).stream()).distinct().toList(),
                issue.evidenceIds().stream().filter(shown).toList(),
                follows(graph, id, relations), approval(publication, id, relations, sources),
                new Unavailable("unavailable", SUMMARY_UNAVAILABLE), metadata);
    }

    /**
     * The handoff issue behind this snapshot issue (same id); its absence means the receipt does not describe the version.
     * Unsupported older receipts are SOURCE_UNAVAILABLE, never read as empty mentions or verdicts.
     */
    private static Obj handoffIssue(Obj bundle, String issueId) {
        for (Obj candidate : bundle.objects("issues")) {
            if (issueId.equals(candidate.string("id"))) return candidate;
        }
        throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
    }

    /**
     * Formats 5–7 keep their original receipt semantics; format 8 also retains reviewed unresolved source times.
     * The importer admits only its exact current schema.
     */
    private static Obj supportedBundle(Obj bundle) {
        if (!bundle.has("schemaVersion") || !bundle.raw("schemaVersion").isString()
                || !BUNDLE_SCHEMAS.contains(bundle.string("schemaVersion"))) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        }
        String schema = bundle.string("schemaVersion");
        if (!Set.of("zoop-graph-handoff-bundle-8", "zoop-graph-handoff-bundle-9").contains(schema)
                && !LegacyRealPackage.isBundleSchema(schema)) {
            for (Obj issue : bundle.objects("issues")) {
                if (issue.objects("mentions").stream().anyMatch(m -> "unresolved".equals(m.string("timePrecision")))
                        || issue.objects("fieldVerdicts").stream().anyMatch(v -> "unsupported-format".equals(v.string("reasonCode")))) {
                    throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
                }
                if (issue.has("geography") && issue.object("geography").objects("basis").stream()
                        .anyMatch(b -> b.strings("countries").isEmpty())) {
                    throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
                }
            }
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

    /** Exact selected owners supply headline proof; incidental source mentions cannot replace them. */
    public static boolean readable(Publication publication, Issue issue, Predicate<String> shown) {
        var owners = publication.issueSources().get(issue.issueId());
        if (owners == null) throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        for (IssueRef ref : Set.copyOf(owners.headlineSources().values())) {
            Obj handoff = handoffIssue(supportedBundle(publication.source(ref.sourceVersionId()).bundle()), ref.issueId());
            if (!headShown(publication.originalIssue(ref), mentionsById(handoff, issue, shown))) return false;
        }
        IssueRef geography = owners.headlineSources().get("geography");
        return publication.originalIssue(geography).geographyEvidenceIds().stream().allMatch(shown);
    }

    private record SourceIssue(Contribution source, Obj issue, Map<String, Obj> mentions) { }

    private static List<SourceIssue> sourceIssues(Publication publication, Issue issue, Predicate<String> shown) {
        var owners = publication.issueSources().get(issue.issueId());
        if (owners == null) throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        List<SourceIssue> result = new ArrayList<>();
        for (IssueRef ref : owners.members()) {
            Contribution source = publication.source(ref.sourceVersionId());
            Obj original = handoffIssue(supportedBundle(source.bundle()), ref.issueId());
            result.add(new SourceIssue(source, original, mentionsById(original, issue, shown)));
        }
        return result;
    }

    private static boolean otherHeadShown(DisplayGraph graph, Publication publication, String id, Relation r,
            Predicate<String> shown) {
        Issue other = graph.issues.get(r.source().equals(id) ? r.target() : r.source());
        return other != null && readable(publication, other, shown);
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

    /** Historical field verdicts and legacy3's explicit metadata-unknown policy both withhold public temporal values. */
    private static Map<String, Set<String>> withheld(Obj handoff, Map<String, String> appIds, String schema) {
        Map<String, Set<String>> out = new HashMap<>();
        for (Obj verdict : handoff.objects("fieldVerdicts")) {
            String appId = appIds.get(producerKey(verdict));
            if (appId != null && WITHHELD.contains(verdict.string("decision"))) {
                out.computeIfAbsent(appId, k -> new HashSet<>()).add(verdict.string("field"));
            }
        }
        if (LegacyRealPackage.METADATA_BUNDLE_SCHEMA.equals(schema)) {
            Obj policy = handoff.object("metadataPolicy");
            for (String field : List.of("eventTime", "period")) {
                if ("unknown".equals(policy.object(field).string("mode"))) {
                    for (String appId : appIds.values()) {
                        out.computeIfAbsent(appId, k -> new HashSet<>()).add(field);
                    }
                }
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
                            m.has("approvalBasis") ? p.bool("roleUnconfirmed") : p.stringOrNull("role") != null))
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
            List<Obj> visibleMentions) {
        Set<String> pairs = evidence.stream().map(e -> e.articleId() + "@" + e.articleVersion()).collect(Collectors.toSet());
        return snapshot.articles().stream().filter(a -> pairs.contains(a.articleId() + "@" + a.version()))
                .sorted(Comparator.comparing((Article a) -> DisplayGraph.publishedAt(a.publishedAt()),
                        Comparator.nullsLast(Comparator.reverseOrder())).thenComparing(Article::articleId))
                .map(a -> new ArticleOut(a.title(), a.articleId(),
                        registry.findVersion(a.articleId(), a.version()).map(VersionRow::publisher).orElse(null), a.url(),
                        a.publishedAt(), articleRelation(a, visibleMentions)))
                .toList();
    }

    private static String articleRelation(Article article, List<Obj> visibleMentions) {
        List<Obj> own = visibleMentions.stream()
                .filter(m -> m.string("articleId").equals(article.articleId())
                        && m.string("articleVersion").equals(article.version()))
                .toList();
        if (own.isEmpty()) return null;
        return own.stream().allMatch(m -> m.bool("background")) ? "PROVIDES_BACKGROUND" : "REPORTS";
    }

    private static RelationOut relation(Relation r, boolean roleUnconfirmed) {
        return new RelationOut(r.relationId(), DisplayGraph.edgeId(r.relationType(), r.source(), r.target()),
                r.relationType(), r.source(), r.target(), r.role(), roleUnconfirmed, r.assertionStatus(), r.evidenceIds());
    }

    /** First nonnull role per company/type; uncertainty is true if any contributing relation has an unconfirmed role. */
    private static List<CompanyLink> companies(DisplayGraph graph, String id, List<Relation> relations, Map<String, Boolean> roleFlags) {
        Map<String, CompanyLink> links = new LinkedHashMap<>();
        for (Relation r : relations) {
            if (!r.source().equals(id) || !DisplayGraph.COMPANY_LINKS.contains(r.relationType())) continue;
            PublicGraphSnapshot.Company company = graph.companies.get(r.target());
            if (company == null) continue;
            links.merge(r.target() + "|" + r.relationType(),
                    new CompanyLink(r.target(), company.label(), r.role(),
                            roleFlags.getOrDefault(r.relationId(), r.role() != null), r.relationType()),
                    (first, next) -> {
                        CompanyLink selected = first.role() != null ? first : next;
                        boolean unconfirmed = first.roleUnconfirmed() || next.roleUnconfirmed();
                        return selected.roleUnconfirmed() == unconfirmed ? selected : new CompanyLink(selected.id(),
                                selected.name(), selected.role(), unconfirmed, selected.relationType());
                    });
        }
        return List.copyOf(links.values());
    }

    private static Map<String, Boolean> legacyRelationRoleFlags(Publication publication, List<Relation> visible) {
        if (publication == null) return Map.of();
        Map<String, Boolean> flags = new HashMap<>();
        for (Relation relation : visible) {
            var owners = publication.relationSources().get(relation.relationId());
            if (owners == null) throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
            for (var ref : publication.selectedRelationSources(relation.relationId())) {
                var source = publication.source(ref.sourceVersionId());
                if (!"legacy-real".equals(source.sourceKind())) {
                    flags.merge(relation.relationId(), relation.role() != null, Boolean::logicalOr);
                    continue;
                }
                Obj original = source.bundle().objects("relations").stream()
                        .filter(r -> r.string("id").equals(ref.relationId())).findFirst()
                        .orElseThrow(() -> new CustomException(ErrorCode.SOURCE_UNAVAILABLE)).object("legacy");
                flags.merge(relation.relationId(), original.has("role_unconfirmed") && original.bool("role_unconfirmed"),
                        Boolean::logicalOr);
            }
        }
        return flags;
    }

    private record ArticleFact(String id, String version, String text, String origin) { }

    private static SourceSupportOut sourceSupport(Publication publication, List<SourceIssue> sources,
            PublicGraphSnapshot snapshot, List<PublicGraphSnapshot.Evidence> evidence) {
        Set<String> pairs = evidence.stream().map(e -> e.articleId() + "\n" + e.articleVersion()).collect(Collectors.toSet());
        List<Article> articles = snapshot.articles().stream()
                .filter(a -> pairs.contains(a.articleId() + "\n" + a.version())).toList();
        if (sources.size() <= 1) return sourceSupport(sources.isEmpty() ? null : sources.getFirst().issue(),
                articles.stream().map(Article::articleId).toList());
        List<ArticleFact> facts = new ArrayList<>();
        for (Article article : articles) {
            Set<String> texts = new HashSet<>(), origins = new HashSet<>();
            boolean unknown = false;
            for (Contribution source : publication.articleSources(article.articleId(), article.version())) {
                Obj fact = source.bundle().objects("articles").stream().filter(a -> article.articleId().equals(a.string("articleId"))
                        && article.version().equals(a.string("articleVersion"))).findFirst()
                        .orElseThrow(() -> new CustomException(ErrorCode.SOURCE_UNAVAILABLE));
                texts.add(fact.string("textSha256"));
                if (!fact.has("origin") || fact.isNull("origin")) unknown = true;
                else origins.add(fact.object("origin").string("originId"));
            }
            if (texts.size() != 1) throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
            facts.add(new ArticleFact(article.articleId(), article.version(), texts.iterator().next(),
                    !unknown && origins.size() == 1 ? origins.iterator().next() : null));
        }
        facts.sort(Comparator.comparing(ArticleFact::id).thenComparing(ArticleFact::version));
        int[] parent = new int[facts.size()];
        Map<String, Integer> origins = new HashMap<>(), texts = new HashMap<>();
        Map<String, Set<String>> duplicates = new java.util.TreeMap<>();
        Set<String> unknown = new TreeSet<>();
        for (int index = 0; index < facts.size(); index++) {
            parent[index] = index;
            ArticleFact fact = facts.get(index);
            if (fact.origin() == null) unknown.add(fact.id());
            else {
                Integer previous = origins.putIfAbsent(fact.origin(), index);
                if (previous != null) parent[root(parent, index)] = root(parent, previous);
            }
            Integer previous = texts.putIfAbsent(fact.text(), index);
            if (previous != null) parent[root(parent, index)] = root(parent, previous);
            duplicates.computeIfAbsent(fact.text(), ignored -> new TreeSet<>()).add(fact.id());
        }
        Map<Integer, Set<String>> lineages = new HashMap<>();
        for (int index = 0; index < facts.size(); index++) {
            Set<String> group = lineages.computeIfAbsent(root(parent, index), ignored -> new HashSet<>());
            if (facts.get(index).origin() != null) group.add(facts.get(index).origin());
        }
        int known = (int) lineages.values().stream().filter(g -> !g.isEmpty()).count();
        Integer independent = unknown.isEmpty() && lineages.values().stream().noneMatch(g -> g.size() > 1) ? known : null;
        List<List<String>> groups = duplicates.values().stream().filter(g -> g.size() > 1).map(List::copyOf)
                .sorted(Comparator.comparing(g -> String.join("\n", g))).toList();
        int articleCount = (int) facts.stream().map(ArticleFact::id).distinct().count();
        boolean oneVersionPerArticle = articleCount == facts.size();
        return new SourceSupportOut(articleCount, oneVersionPerArticle ? known : null,
                List.copyOf(unknown), oneVersionPerArticle ? independent : null, groups);
    }

    private static int root(int[] parents, int index) {
        while (parents[index] != index) index = parents[index];
        return index;
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

    /**
     * {@code admin-review} when a company relation this read shows (INVOLVES from this issue, already cut by asOf, exclusions
     * and current evidence rights) rests on an operator's final approval in the receipt; null otherwise, and always for a
     * synthetic fixture (no receipt). Only the receipt literal is read; who approved and when stay in the receipt and the admin
     * decision log. Formats 5 to 7 all carry the literal (added in bundle 4); a receipt without relations is not describable.
     */
    private static ApprovalOut approval(Publication publication, String id, List<Relation> relations,
            List<SourceIssue> sources) {
        if (publication == null) return null;
        Set<ApprovalOut> approvals = new HashSet<>();
        for (SourceIssue source : sources) {
            if ("legacy-real".equals(source.source().sourceKind())) {
                approvals.add(source.mentions().values().stream()
                        .anyMatch(m -> "review-rule:R1@2".equals(m.string("approvalBasis")))
                        ? new ApprovalOut("review-rule", "자동 검수 규칙", "issue", "R1@2") : null);
                continue;
            }
            Obj bundle = source.source().bundle();
            if (!bundle.has("relations") || !bundle.raw("relations").isArray())
                throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
            Set<String> originalIds = new HashSet<>();
            for (Relation relation : relations) {
                if (!"INVOLVES".equals(relation.relationType()) || !id.equals(relation.source())) continue;
                var owners = publication.relationSources().get(relation.relationId());
                if (owners == null) throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
                publication.selectedRelationSources(relation.relationId()).stream()
                        .filter(r -> r.sourceVersionId().equals(source.source().sourceVersionId()))
                        .forEach(r -> originalIds.add(r.relationId()));
            }
            if (originalIds.isEmpty()) continue;
            approvals.add(bundle.objects("relations").stream().anyMatch(r -> originalIds.contains(r.string("id"))
                    && r.has("provenance")
                    && OPERATOR_APPROVED.equals(r.object("provenance").stringOrNull("s3SemanticValidation")))
                    ? ADMIN_APPROVAL : null);
        }
        return approvals.size() == 1 ? approvals.iterator().next() : null;
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
