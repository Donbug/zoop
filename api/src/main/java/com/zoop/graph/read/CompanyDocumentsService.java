package com.zoop.graph.read;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.response.Metadata;
import com.zoop.document.evidence.dto.EvidenceResponse;
import com.zoop.document.evidence.service.EvidenceService;
import com.zoop.document.repository.ArticleRow;
import com.zoop.document.repository.DocumentRegistryRepository;
import com.zoop.document.repository.VersionRow;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Issue;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.Base64;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.dao.DataAccessException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.ObjectMapper;

/** Read-only company documents from one pinned public graph version. */
@Service
public class CompanyDocumentsService {
    public record EventRef(String eventId, String title, String relationType) { }
    public record Quote(String evidenceId, String quote, Boolean quoteVerified) { }
    public record Document(String id, String title, String publisher, String url, Instant publishedAt, String kind,
            List<EventRef> events, List<Quote> quotes, Object sentiment, String documentVersion,
            Object documentSummary, Object analysisStatus, Object analysisProvenance, String resultVersion) { }
    public record Response(List<Document> items, Metadata metadata, String nextCursor) { }
    record Cursor(String companyId, String kind, String from, String to, int limit, String graphVersion,
            String asOf, String pinnedAt, String lastArticleId, String lastPublishedAt, String round, Boolean filtered) { }
    private record DocumentKey(String articleId, String articleVersion) { }
    private record Candidate(PublicGraphSnapshot.Article snapshot, ArticleRow article, VersionRow version,
            List<EventRef> events, Set<String> evidenceIds, Instant published) { }

    private final PublicGraphReader reader;
    private final NamedParameterJdbcTemplate jdbc;
    private final DocumentRegistryRepository registry;
    private final EvidenceService evidence;
    private final CompanyDocumentAnalysisReader analyses;
    private final ObjectMapper mapper;

    public CompanyDocumentsService(PublicGraphReader reader, NamedParameterJdbcTemplate jdbc,
            DocumentRegistryRepository registry, EvidenceService evidence, CompanyDocumentAnalysisReader analyses,
            ObjectMapper mapper) {
        this.reader = reader;
        this.jdbc = jdbc;
        this.registry = registry;
        this.evidence = evidence;
        this.analyses = analyses;
        this.mapper = mapper;
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public Response list(String companyId, String kind, String from, String to, String round, String graphVersion,
            String asOf, String cursor, Integer limit, String requestId) {
        try {
            return read(companyId, kind, from, to, round, graphVersion, asOf, cursor, limit, requestId);
        } catch (DataAccessException error) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, error);
        }
    }

    private Response read(String companyId, String kind, String from, String to, String round, String graphVersion,
            String asOf, String cursor, Integer limit, String requestId) {
        if (companyId == null || companyId.isBlank() || (kind != null && !Set.of("news", "disclosure").contains(kind))
                || (limit != null && limit < 1) || (round != null && round.isBlank())) throw invalid();
        Instant start = from == null ? null : EventListService.bound(from, false);
        Instant end = to == null ? null : EventListService.bound(to, true);
        if (start != null && end != null && !start.isBefore(end)) throw invalid();
        Instant requestedAsOf = asOf == null ? null : parseAsOf(asOf);
        Cursor after = cursor == null ? null : decode(cursor);
        if (after != null && (!companyId.equals(after.companyId()) || !Objects.equals(kind, after.kind())
                || !Objects.equals(from, after.from()) || !Objects.equals(to, after.to())
                || !Objects.equals(round, after.round())
                || !Objects.equals(asOf, after.asOf()) || (limit != null && limit != after.limit())
                || (graphVersion != null && !graphVersion.equals(after.graphVersion())))) {
            throw new CustomException(ErrorCode.INVALID_CURSOR);
        }
        requireCatalog(companyId);
        // A later page without a round or asOf keeps the first page's pinned read, never re-read as a version-only address.
        PublicGraphReader.Pinned pinned = after != null && round == null && requestedAsOf == null
                ? reader.readPinned(after.graphVersion(), Instant.parse(after.pinnedAt()), Boolean.TRUE.equals(after.filtered()))
                : reader.read(round, after == null ? graphVersion : after.graphVersion(), requestedAsOf);
        DisplayGraph graph = pinned.graph();
        Map<DocumentKey, PublicGraphSnapshot.Article> snapshotArticles = new HashMap<>();
        Map<String, List<PublicGraphSnapshot.Article>> articlesById = new HashMap<>();
        for (var article : graph.snapshot.articles()) {
            snapshotArticles.put(new DocumentKey(article.articleId(), article.version()), article);
            articlesById.computeIfAbsent(article.articleId(), ignored -> new ArrayList<>()).add(article);
        }
        Map<String, PublicGraphSnapshot.Evidence> snapshotEvidence = new HashMap<>();
        for (var span : graph.snapshot.evidence()) snapshotEvidence.put(span.evidenceId(), span);
        Map<DocumentKey, List<EventRef>> events = new LinkedHashMap<>();
        Map<DocumentKey, Set<String>> evidenceIds = new LinkedHashMap<>();
        for (Issue issue : graph.issuesOf(companyId)) {
            if (end != null && !visibleAtTo(issue, companyId, end, graph, snapshotArticles, snapshotEvidence)) continue;
            EventRef event = new EventRef(issue.issueId(), issue.label(), null);
            Set<DocumentKey> issueArticles = new LinkedHashSet<>();
            for (var mention : issue.mentions()) {
                DocumentKey key = new DocumentKey(mention.articleId(), mention.articleVersion());
                if (snapshotArticles.containsKey(key)) issueArticles.add(key);
            }
            // Older/fixture snapshots without mentions can be resolved only when the article has one pinned version.
            if (issueArticles.isEmpty() && issue.mentions().isEmpty()) {
                for (String articleId : issue.articleIds()) {
                    List<PublicGraphSnapshot.Article> versions = articlesById.getOrDefault(articleId, List.of());
                    if (versions.size() == 1) {
                        var article = versions.get(0);
                        issueArticles.add(new DocumentKey(article.articleId(), article.version()));
                    }
                }
            }
            for (DocumentKey key : issueArticles)
                events.computeIfAbsent(key, ignored -> new ArrayList<>()).add(event);
            for (String evidenceId : issue.evidenceIds()) {
                PublicGraphSnapshot.Evidence span = snapshotEvidence.get(evidenceId);
                if (span != null) {
                    DocumentKey key = new DocumentKey(span.articleId(), span.articleVersion());
                    if (issueArticles.contains(key))
                        evidenceIds.computeIfAbsent(key, ignored -> new LinkedHashSet<>()).add(evidenceId);
                }
            }
        }
        List<Candidate> candidates = new ArrayList<>();
        for (var entry : events.entrySet()) {
            PublicGraphSnapshot.Article snapshot = snapshotArticles.get(entry.getKey());
            ArticleRow article = registry.findArticle(entry.getKey().articleId()).orElse(null);
            if (article == null || !"available".equals(article.accessStatus())) continue;
            if (kind != null && !kind.equals(article.kind())) continue;
            VersionRow version = registry.findVersion(snapshot.articleId(), snapshot.version()).orElse(null);
            if (version == null) continue;
            Instant published = DisplayGraph.publishedAt(snapshot.publishedAt());
            // A bounded range cannot establish whether an unknown publication happened inside it.
            if (published == null && (start != null || end != null)) continue;
            Instant publishedEnd = snapshot.publishedAt() != null && snapshot.publishedAt().length() == 10
                    ? published.plusSeconds(24 * 60 * 60) : published == null ? null : published.plusNanos(1);
            if (published != null && ((start != null && !publishedEnd.isAfter(start))
                    || (end != null && !published.isBefore(end)))) continue;
            candidates.add(new Candidate(snapshot, article, version, List.copyOf(entry.getValue()),
                    evidenceIds.getOrDefault(entry.getKey(), Set.of()), published));
        }
        candidates.sort(Comparator.comparing(Candidate::published, Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing(item -> item.snapshot().articleId())
                .thenComparing(item -> item.snapshot().version()));
        // The list contract returns one row per article: choose its newest pinned publication, then version id as a stable tie-breaker.
        Set<String> selectedArticleIds = new LinkedHashSet<>();
        candidates.removeIf(candidate -> !selectedArticleIds.add(candidate.snapshot().articleId()));
        Instant lastPublished = after == null || after.lastPublishedAt() == null ? null
                : Instant.parse(after.lastPublishedAt());
        int startIndex = 0;
        if (after != null) {
            while (startIndex < candidates.size() && comparePosition(candidates.get(startIndex),
                    after.lastArticleId(), lastPublished) <= 0) startIndex++;
        }
        int pageLimit = limit != null ? limit : after != null ? after.limit() : candidates.size() - startIndex;
        int pageEnd = (int) Math.min(candidates.size(), (long) startIndex + pageLimit);
        List<Document> page = new ArrayList<>();
        for (Candidate candidate : candidates.subList(startIndex, pageEnd)) {
            List<Quote> quotes = new ArrayList<>();
            boolean sourceAuthorized = false;
            for (String evidenceId : candidate.evidenceIds()) {
                try {
                    EvidenceResponse visible = evidence.read(evidenceId, round, pinned.selected().version().id(),
                            round == null ? asOf : pinned.selected().asOf().toString(),
                            companyId, requestId);
                    boolean sameSnapshot = (asOf == null && round == null) || visible.metadata() != null
                            && pinned.selected().version().id().equals(visible.metadata().graphVersion())
                            && pinned.selected().asOf().equals(visible.metadata().asOf());
                    boolean sameDocument = sameSnapshot && candidate.snapshot().articleId().equals(visible.articleId())
                            && candidate.snapshot().version().equals(visible.articleVersion());
                    if (sameDocument) {
                        sourceAuthorized = true;
                        if (visible.eventIds().stream().anyMatch(id -> candidate.events().stream()
                                .anyMatch(event -> event.eventId().equals(id))))
                            quotes.add(new Quote(evidenceId, visible.quote(), visible.quoteVerified()));
                    }
                } catch (CustomException error) {
                    if (error.getErrorCode() != ErrorCode.EVIDENCE_UNAVAILABLE
                            && error.getErrorCode() != ErrorCode.RESOURCE_NOT_FOUND) throw error;
                }
            }
            // A current source grant must authorize document metadata as well as any quote we display.
            if (!sourceAuthorized) continue;
            // A date-only publication is not promoted to an invented date-time on the wire.
            Instant publishedAt = "datetime".equals(candidate.version().publicationPrecision())
                    ? candidate.version().publishedAt() : null;
            var analysis = analyses.read(candidate.article(), candidate.version(), companyId, requestId,
                    requestedAsOf != null || graphVersion != null || round != null);
            page.add(new Document(candidate.snapshot().articleId(), candidate.snapshot().title(),
                    candidate.version().publisher(), candidate.snapshot().url(), publishedAt, candidate.article().kind(),
                    candidate.events(), List.copyOf(quotes), analysis.sentiment(), candidate.snapshot().version(),
                    analysis.summary(), analysis.status(), analysis.provenance(), analysis.resultVersion()));
        }
        String pinnedAt = after != null && asOf == null ? after.pinnedAt() : pinned.selected().asOf().toString();
        Candidate last = pageEnd == candidates.size() ? null : candidates.get(pageEnd - 1);
        String next = last == null ? null : encode(new Cursor(companyId, kind, from, to, pageLimit,
                pinned.selected().version().id(), asOf, pinnedAt, last.snapshot().articleId(),
                last.published() == null ? null : last.published().toString(), round, pinned.selected().asOfRequested()));
        return new Response(List.copyOf(page), new Metadata(pinned.selected().source(), Instant.parse(pinnedAt),
                pinned.selected().version().id(), requestId, false, List.of()), next);
    }

    private void requireCatalog(String id) {
        Integer count = jdbc.queryForObject("SELECT count(*) FROM companies WHERE id = :id",
                new MapSqlParameterSource("id", id), Integer.class);
        if (count == null || count == 0) throw new CustomException(ErrorCode.RESOURCE_NOT_FOUND);
    }

    /** Apply the prototype's to-time graph cutoff inside the already selected public version. */
    private static boolean visibleAtTo(Issue issue, String companyId, Instant end, DisplayGraph graph,
            Map<DocumentKey, PublicGraphSnapshot.Article> articles,
            Map<String, PublicGraphSnapshot.Evidence> evidence) {
        if (!publishedBeforeEnd(issue.latestPublishedAt(), end)) return false;
        Set<DocumentKey> articleRefs = new LinkedHashSet<>();
        for (var mention : issue.mentions())
            articleRefs.add(new DocumentKey(mention.articleId(), mention.articleVersion()));
        if (articleRefs.isEmpty() && issue.mentions().isEmpty()) {
            for (String articleId : issue.articleIds()) {
                List<PublicGraphSnapshot.Article> versions = graph.snapshot.articles().stream()
                        .filter(article -> article.articleId().equals(articleId)).toList();
                if (versions.size() != 1) return false;
                var article = versions.get(0);
                articleRefs.add(new DocumentKey(article.articleId(), article.version()));
            }
        }
        if (articleRefs.stream().anyMatch(key -> {
            var article = articles.get(key);
            return article == null || !publishedBeforeEnd(article.publishedAt(), end);
        })) return false;
        return graph.snapshot.relations().stream().filter(relation -> relation.source().equals(issue.issueId())
                && relation.target().equals(companyId) && DisplayGraph.COMPANY_LINKS.contains(relation.relationType()))
                .anyMatch(relation -> relation.evidenceIds().stream().allMatch(id -> {
                    var span = evidence.get(id);
                    var article = span == null ? null : articles.get(new DocumentKey(span.articleId(), span.articleVersion()));
                    return article != null && publishedBeforeEnd(article.publishedAt(), end);
                }) && (!"STRUCTURALLY_RELATED_TO".equals(relation.relationType()) || relation.basis().stream()
                        .anyMatch(basis -> Instant.parse(basis.verifiedAt()).isBefore(end))));
    }

    private static boolean publishedBeforeEnd(String value, Instant end) {
        Instant published = DisplayGraph.publishedAt(value);
        return published != null && published.isBefore(end);
    }

    private String encode(Cursor value) {
        return Base64.getUrlEncoder().withoutPadding().encodeToString(mapper.writeValueAsBytes(value));
    }

    private Cursor decode(String value) {
        try {
            Cursor result = mapper.readValue(new String(Base64.getUrlDecoder().decode(value), StandardCharsets.UTF_8), Cursor.class);
            if (result.graphVersion() == null || result.pinnedAt() == null || result.limit() < 1
                    || result.lastArticleId() == null || result.lastArticleId().isBlank())
                throw new CustomException(ErrorCode.INVALID_CURSOR);
            Instant.parse(result.pinnedAt());
            if (result.lastPublishedAt() != null) Instant.parse(result.lastPublishedAt());
            return result;
        } catch (CustomException error) {
            throw error;
        } catch (RuntimeException error) {
            throw new CustomException(ErrorCode.INVALID_CURSOR, error);
        }
    }

    private static Instant parseAsOf(String value) {
        try {
            return OffsetDateTime.parse(value).toInstant();
        } catch (DateTimeParseException error) {
            throw invalid();
        }
    }

    private static int comparePosition(Candidate candidate, String id, Instant published) {
        int time = Comparator.nullsLast(Comparator.<Instant>reverseOrder()).compare(candidate.published(), published);
        return time != 0 ? time : candidate.snapshot().articleId().compareTo(id);
    }

    private static CustomException invalid() { return new CustomException(ErrorCode.INVALID_REQUEST); }
}
