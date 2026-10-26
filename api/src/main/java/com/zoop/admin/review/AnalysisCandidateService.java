package com.zoop.admin.review;

import java.time.Clock;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

import com.zoop.admin.review.AnalysisCandidates.CandidateArticle;
import com.zoop.admin.review.AnalysisCandidates.CandidateCompany;
import com.zoop.admin.review.AnalysisCandidates.CandidateDetail;
import com.zoop.admin.review.AnalysisCandidates.CandidateEvidence;
import com.zoop.admin.review.AnalysisCandidates.CandidateList;
import com.zoop.admin.review.AnalysisCandidates.CandidateMention;
import com.zoop.admin.review.AnalysisCandidates.CandidateRelation;
import com.zoop.admin.review.AnalysisCandidates.CandidateRow;
import com.zoop.admin.review.AnalysisCandidates.ReviewDecisionOut;
import com.zoop.admin.review.AnalysisCandidates.VerdictOut;
import com.zoop.admin.review.AnalysisCandidates.VerificationOut;
import com.zoop.admin.review.JdbcCandidateRepository.Candidate;
import com.zoop.admin.review.JdbcCandidateRepository.Relation;
import com.zoop.admin.review.JdbcReviewRepository.SyncUnit;
import com.zoop.admin.review.PublishedCandidates.Shown;
import com.zoop.ai.AiClientException;
import com.zoop.ai.extraction.ExtractionClient;
import com.zoop.ai.extraction.UntrustedExtractionPayload;
import com.zoop.ai.relation.RelationClient;
import com.zoop.ai.relation.RelationUpstream;
import com.zoop.ai.relation.UntrustedRelationPayload;
import com.zoop.auth.service.CsrfKeyRing;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import com.zoop.common.json.StrictJson.Obj;
import com.zoop.document.repository.ArticleRow;
import com.zoop.document.repository.DocumentRegistryRepository;
import com.zoop.document.repository.VersionRow;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.dao.DataAccessException;
import org.springframework.stereotype.Service;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * {@code listAnalysisCandidates} and {@code getAnalysisCandidate} (#132, A-ADM-03). The list reads only the app projection
 * ({@code review_targets}, written by the review-target sync), so it answers while the AI service is down. The detail reads the
 * S2 and S3 results again (ERD v6 section 26: no copied detail JSON), the S2 content pinned by the analyze-plan unit's hash, and
 * the cited articles from the app registry: the S2-1 document id is the app article id (`DocumentImporter`), so a document the
 * operator imported has its title and URL, one that was not has none, and one whose access was withdrawn has its quotes hidden.
 *
 * <p>Not produced yet, and null rather than invented: {@code policyVersion} (no AI source), {@code rule} (the publication rules
 * are not evaluated on candidates yet), a company's app id (the source ids are the AI's, not the catalogue's).
 */
@Service
public class AnalysisCandidateService {
    private static final Logger log = LoggerFactory.getLogger(AnalysisCandidateService.class);
    static final int DEFAULT_LIMIT = 20;
    static final int MAX_LIMIT = 100;
    private static final Set<String> STATUSES = Set.of("ALLOW", "HOLD", "REJECT");
    private static final Set<String> DECISIONS = Set.of("none", "allow", "reject");
    private static final String AVAILABLE = "available";

    private final JdbcCandidateRepository candidates;
    private final JdbcReviewRepository reviews;
    private final PublishedCandidates published;
    private final DocumentRegistryRepository registry;
    private final ObjectProvider<ExtractionClient> extraction;
    private final ObjectProvider<RelationClient> relation;
    private final ObjectProvider<ReviewTargetSync> sync;
    private final ObjectMapper mapper;
    private final CsrfKeyRing keys;
    private final Clock clock;

    public AnalysisCandidateService(JdbcCandidateRepository candidates, JdbcReviewRepository reviews,
            PublishedCandidates published, DocumentRegistryRepository registry, ObjectProvider<ExtractionClient> extraction,
            ObjectProvider<RelationClient> relation, ObjectProvider<ReviewTargetSync> sync, ObjectMapper mapper,
            CsrfKeyRing keys, Clock clock) {
        this.candidates = candidates;
        this.reviews = reviews;
        this.published = published;
        this.registry = registry;
        this.extraction = extraction;
        this.relation = relation;
        this.sync = sync;
        this.mapper = mapper;
        this.keys = keys;
        this.clock = clock;
    }

    public CandidateList list(String adminId, String status, String decision, Boolean active, Boolean onGraph, Boolean rule,
            String q, String cursor, Integer requestedLimit, String requestId) {
        if (status != null && !STATUSES.contains(status)) throw new CustomException(ErrorCode.INVALID_REQUEST);
        if (decision != null && !DECISIONS.contains(decision)) throw new CustomException(ErrorCode.INVALID_REQUEST);
        if (requestedLimit != null && (requestedLimit < 1 || requestedLimit > MAX_LIMIT)) {
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        }
        String query = q == null || q.isBlank() ? null : q.strip();
        if (query != null && query.length() > 200) throw new CustomException(ErrorCode.INVALID_REQUEST);
        String filters = String.join("|", String.valueOf(status), String.valueOf(decision), String.valueOf(active),
                String.valueOf(onGraph), String.valueOf(rule), String.valueOf(query));
        var position = CandidateCursor.decode(mapper, keys, cursor, adminId, filters, requestedLimit, MAX_LIMIT);
        int limit = requestedLimit != null ? requestedLimit : position == null ? DEFAULT_LIMIT : position.limit();
        Optional<Shown> shown = published.current(requestId);
        if (onGraph != null && shown.isEmpty()) throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        try {
            Map<String, Integer> counts = candidates.counts();
            // No rule is evaluated on a candidate yet (rule is always null), so asking for rule-covered ones finds none.
            if (Boolean.TRUE.equals(rule)) return new CandidateList(List.of(), null, counts, clock.instant());
            JdbcCandidateRepository.Filter filter = new JdbcCandidateRepository.Filter(status, decision, active, onGraph,
                    query, shown.map(s -> pairs(s.relations())).orElse(List.of()),
                    shown.map(s -> pairs(s.events())).orElse(List.of()));
            List<Candidate> rows = candidates.page(filter, position == null ? null : position.at(),
                    position == null ? null : position.id(), limit + 1);
            boolean hasNext = rows.size() > limit;
            List<Candidate> page = hasNext ? rows.subList(0, limit) : rows;
            Map<String, List<Relation>> relations = candidates.relations(page);
            Map<String, List<ReviewDecisionOut>> decisions = candidates.decisions(relations.values().stream()
                    .flatMap(List::stream).map(Relation::id).toList());
            List<CandidateRow> items = page.stream().map(c -> row(c, relations.get(c.id()), decisions, shown)).toList();
            String next = null;
            if (hasNext) {
                Candidate last = page.getLast();
                next = CandidateCursor.encode(mapper, keys, adminId, filters, limit, last.updatedAt(), last.id());
            }
            return new CandidateList(items, next, counts, clock.instant());
        } catch (DataAccessException unavailable) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, unavailable);
        }
    }

    public CandidateDetail get(String candidateId, String requestId) {
        Candidate candidate;
        try {
            candidate = candidates.candidate(candidateId).orElseThrow(() -> new CustomException(ErrorCode.RESOURCE_NOT_FOUND));
        } catch (DataAccessException unavailable) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, unavailable);
        }
        Sources sources = sources(candidate);
        List<Relation> rows = candidates.relations(List.of(candidate)).get(candidate.id());
        Map<String, Obj> s3 = new HashMap<>();
        for (Obj item : sources.s3().objects("relations")) {
            if (item.has("relationCandidateId")) s3.put(item.string("relationCandidateId"), item);
        }
        // A newer AI revision than the projection: refresh it first, so the expected values a decision sends are current.
        boolean stale = rows.stream().anyMatch(r -> s3.containsKey(r.relationCandidateId())
                && !r.sourceRevision().equals(s3.get(r.relationCandidateId()).string("sourceRevision")));
        ReviewTargetSync refresher = sync.getIfUnique();
        if (stale && refresher != null) {
            try {
                refresher.sync(sources.unit().upstream(), sources.unit().s2ResultSha256(), sources.s3Payload());
                candidate = candidates.candidate(candidateId)
                        .orElseThrow(() -> new CustomException(ErrorCode.RESOURCE_NOT_FOUND));
                rows = candidates.relations(List.of(candidate)).get(candidate.id());
            } catch (RuntimeException notRefreshed) {
                // The projection stays as it was; a decision with its older expected values is refused (409), never wrong.
                log.warn("candidate {} projection not refreshed: {}", candidateId, notRefreshed.getClass().getSimpleName());
            }
        }
        Obj event = event(sources.s2(), candidate.candidateId());
        Obj mention = event == null ? null : event.object("mention");
        Optional<Shown> shown = published.current(requestId);
        List<String> targetIds = new ArrayList<>(rows.stream().map(Relation::id).toList());
        targetIds.add(candidate.id());
        Map<String, List<ReviewDecisionOut>> decisions = candidates.decisions(targetIds);
        CandidateRow row = row(candidate, rows, decisions, shown);

        List<Obj> evidenceCitations = event != null ? event.objects("citations")
                : rows.isEmpty() || !s3.containsKey(rows.getFirst().relationCandidateId()) ? List.of()
                : s3.get(rows.getFirst().relationCandidateId()).objects("citations");
        Map<String, Article> articles = new LinkedHashMap<>();
        List<CandidateEvidence> evidence = new ArrayList<>();
        for (Obj citation : evidenceCitations) evidence.add(evidence(citation, articles));
        List<CandidateRelation> relationsOut = new ArrayList<>();
        List<VerdictOut> verdicts = new ArrayList<>();
        for (Relation r : rows) {
            Obj item = s3.get(r.relationCandidateId());
            if (item == null) continue;
            for (Obj citation : item.objects("citations")) article(citation.string("documentId"), citation.string("documentVersion"), articles);
            relationsOut.add(relation(r, item, mention, decisions, shown));
            verdicts.addAll(verdicts(r.relationCandidateId(), item));
        }
        List<ReviewDecisionOut> history = targetIds.stream().flatMap(id -> decisions.getOrDefault(id, List.of()).stream())
                .sorted((a, b) -> Long.compare(b.id(), a.id())).toList();
        return new CandidateDetail(row.title(), row.candidateId(), candidate.sourceVersion(), null, row.issueId(),
                row.status(), row.active(), null, row.action(), row.target(), row.eventTime(), row.companies(),
                row.relationTypes(), row.evidenceCount(), row.reasons(), row.onUserGraph(), row.decision(), null,
                mention == null ? null : mention(mention), articles.values().stream().filter(a -> a.out() != null)
                        .map(Article::out).toList(), evidence, relationsOut,
                new VerificationOut(null, null, null, null, verdicts, List.of(), List.of()), null, history,
                graphDb(candidate, rows, row.onUserGraph(), shown));
    }

    // ---- list row

    private CandidateRow row(Candidate c, List<Relation> relations, Map<String, List<ReviewDecisionOut>> decisions,
            Optional<Shown> shown) {
        List<Relation> own = relations == null ? List.of() : relations;
        boolean onGraph = shown.map(s -> own.stream().anyMatch(r -> s.relation(r.s3JobId(), r.relationCandidateId()))
                || (c.s2JobId() != null && s.event(c.s2JobId(), c.candidateId()))).orElse(false);
        ReviewDecisionOut latest = own.stream().flatMap(r -> decisions.getOrDefault(r.id(), List.of()).stream())
                .max((a, b) -> Long.compare(a.id(), b.id())).orElse(null);
        return new CandidateRow(c.title(), c.id(), c.issueId(), c.status(), c.active(), null, c.action(), c.target(),
                c.eventTime(), companies(c.companiesJson()), c.relationTypes(),
                c.evidenceCount() == null ? 0 : c.evidenceCount(), c.reasons(), onGraph, latest, null);
    }

    private List<CandidateCompany> companies(String json) {
        if (json == null) return List.of();
        List<CandidateCompany> out = new ArrayList<>();
        for (JsonNode node : mapper.readTree(json).values()) {
            out.add(new CandidateCompany(null, node.get("name").stringValue(), text(node.get("role"))));
        }
        return out;
    }

    private static String text(JsonNode node) {
        return node == null || node.isNull() ? null : node.stringValue();
    }

    private static List<String[]> pairs(Set<String> keys) {
        return keys.stream().map(key -> key.split("\n", 2)).toList();
    }

    // ---- detail sources

    private record Sources(Unit unit, Obj s2, Obj s3, UntrustedRelationPayload s3Payload) {
    }

    private record Unit(RelationUpstream upstream, String s2ResultSha256) {
    }

    /** The S3 result of the candidate's job and the S2 result the unit pinned by hash; anything else is SOURCE_UNAVAILABLE. */
    private Sources sources(Candidate candidate) {
        ExtractionClient s2Client = extraction.getIfUnique();
        RelationClient s3Client = relation.getIfUnique();
        if (s2Client == null || s3Client == null) throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        try {
            SyncUnit unit = reviews.unitOf(candidate.s3JobId())
                    .orElseThrow(() -> new CustomException(ErrorCode.SOURCE_UNAVAILABLE));
            UntrustedRelationPayload s3 = s3Client.result(unit.s3JobId()).readyPayload()
                    .orElseThrow(() -> new CustomException(ErrorCode.SOURCE_UNAVAILABLE));
            UntrustedExtractionPayload s2 = s2Client.result(unit.s2JobId()).readyPayload()
                    .orElseThrow(() -> new CustomException(ErrorCode.SOURCE_UNAVAILABLE));
            if (!s3.jobId().equals(unit.s3JobId()) || !s3.inputDigest().equals(unit.s3InputDigest())
                    || !s2.jobId().equals(unit.s2JobId()) || !s2.inputDigest().equals(unit.s2InputDigest())
                    || !Canonical.sha256(s2.untrustedJson()).equals(unit.s2ResultSha256())) {
                throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
            }
            return new Sources(new Unit(new RelationUpstream(unit.s2JobId(), unit.s2InputDigest()), unit.s2ResultSha256()),
                    StrictJson.parseObject(s2.untrustedJson()), StrictJson.parseObject(s3.untrustedJson()), s3);
        } catch (AiClientException | StrictJson.Malformed | DataAccessException unavailable) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, unavailable);
        }
    }

    private static Obj event(Obj s2, String candidateId) {
        if (!ReviewTargetReader.EVENT_CANDIDATE_ID.matcher(candidateId).matches()) return null;
        for (Obj item : s2.objects("eventCandidates")) {
            if (item.has("eventCandidateId") && candidateId.equals(item.string("eventCandidateId"))) return item;
        }
        throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
    }

    // ---- detail parts

    private static CandidateMention mention(Obj mention) {
        List<CandidateCompany> participants = new ArrayList<>();
        for (Obj p : mention.objects("participants")) {
            participants.add(new CandidateCompany(null, p.string("name"), p.has("role") ? p.stringOrNull("role") : null));
        }
        return new CandidateMention(mention.string("title"), mention.string("mentionId"), mention.string("action"),
                mention.stringOrNull("target"), mention.stringOrNull("eventTime"), mention.stringOrNull("period"),
                mention.stringOrNull("assertionStatus"), mention.bool("background"), mention.strings("countries"),
                mention.strings("keywords"), participants);
    }

    /** What the app registry says about one cited document version; {@code out} is null when the app does not have it. */
    private record Article(CandidateArticle out, boolean withdrawn) {
    }

    private Article article(String documentId, String documentVersion, Map<String, Article> articles) {
        return articles.computeIfAbsent(documentId + "\n" + documentVersion, key -> {
            Optional<VersionRow> version = registry.findVersion(documentId, documentVersion);
            if (version.isEmpty()) return new Article(null, false);
            Optional<ArticleRow> article = registry.findArticle(documentId);
            boolean withdrawn = article.isEmpty() || !AVAILABLE.equals(article.get().accessStatus());
            VersionRow v = version.get();
            // The contract's publishedAt is a date-time; a day-precision version is never widened to a guessed midnight.
            String publishedAt = v.publishedAt() != null ? v.publishedAt().toString() : null;
            return new Article(new CandidateArticle(v.title(), documentId, v.publisher(), v.url(), publishedAt), withdrawn);
        });
    }

    private CandidateEvidence evidence(Obj citation, Map<String, Article> articles) {
        String documentId = citation.string("documentId");
        String documentVersion = citation.string("documentVersion");
        Article article = article(documentId, documentVersion, articles);
        CandidateArticle out = article.out();
        return new CandidateEvidence(documentId, documentVersion, citation.count("start"), citation.count("end"),
                article.withdrawn() ? null : citation.string("quote"), out == null ? null : out.title(),
                out == null ? null : out.url());
    }

    private static CandidateRelation relation(Relation r, Obj item, Obj mention, Map<String, List<ReviewDecisionOut>> decisions,
            Optional<Shown> shown) {
        Obj subject = item.object("subject");
        Obj object = item.object("object");
        String role = null;
        if (mention != null) {
            Set<String> companies = new LinkedHashSet<>();
            for (Obj endpoint : List.of(subject, object)) {
                if ("company".equals(endpoint.string("kind"))) companies.add(endpoint.string("ref"));
            }
            for (Obj p : mention.objects("participants")) {
                if (p.has("companyId") && !p.isNull("companyId") && companies.contains(p.string("companyId"))) {
                    role = p.string("role");
                    break;
                }
            }
        }
        List<ReviewDecisionOut> own = decisions.getOrDefault(r.id(), List.of());
        return new CandidateRelation(r.relationCandidateId(), r.sourceVersion(), r.sourceRevision(), item.string("type"),
                subject.string("ref"), object.string("ref"), role,
                mention == null ? null : mention.stringOrNull("assertionStatus"), item.objects("citations").size(),
                shown.map(s -> s.relation(r.s3JobId(), r.relationCandidateId())).orElse(false),
                own.isEmpty() ? null : own.getFirst());
    }

    /** The automatic verdicts in the relation's AI event chain ({@code history[].kind=verdict}), oldest first. */
    private static List<VerdictOut> verdicts(String relationCandidateId, Obj item) {
        List<VerdictOut> out = new ArrayList<>();
        if (!item.has("history")) return out;
        for (Obj event : item.objects("history")) {
            if (!"verdict".equals(event.string("kind"))) continue;
            List<String> codes = new ArrayList<>();
            if (event.has("reasons")) for (Obj reason : event.objects("reasons")) codes.add(reason.string("code"));
            out.add(new VerdictOut(relationCandidateId, event.stringOrNull("eligibility"), String.join(",", codes)));
        }
        return out;
    }

    /**
     * Where the candidate stands against the public graph (user decision 2026-10-26): {@code reflected} users see it,
     * {@code excluded} it was published in the active version and is hidden now (a disclosure exclusion or an evidence that can
     * no longer be read), {@code pending} an operator approved a relation that is not in the active version yet (the next
     * handoff and import), {@code not_stored} anything else (an automatic pass nobody handed off included), {@code unknown} the
     * active version cannot be read.
     */
    private static String graphDb(Candidate c, List<Relation> relations, boolean onGraph, Optional<Shown> shown) {
        if (shown.isEmpty()) return "unknown";
        if (onGraph) return "reflected";
        Shown s = shown.get();
        if (relations.stream().anyMatch(r -> s.excludedRelation(r.s3JobId(), r.relationCandidateId()))
                || (c.s2JobId() != null && s.excludedEvent(c.s2JobId(), c.candidateId()))) return "excluded";
        return relations.stream().anyMatch(r -> r.operatorApproved() && "ALLOW".equals(r.status())) ? "pending" : "not_stored";
    }
}
