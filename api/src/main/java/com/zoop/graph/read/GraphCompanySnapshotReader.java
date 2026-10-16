package com.zoop.graph.read;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.company.graph.CompanyGraphReadRequest;
import com.zoop.company.graph.CompanyGraphSnapshot;
import com.zoop.company.graph.CompanyGraphSnapshot.BasisOut;
import com.zoop.company.graph.CompanyGraphSnapshot.CompanyIssueRef;
import com.zoop.company.graph.CompanyGraphSnapshotReader;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Article;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Basis;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Relation;
import java.time.Instant;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.function.Function;
import java.util.stream.Collectors;
import org.springframework.stereotype.Component;

/**
 * getCompany's graph sections from the same pinned, filtered snapshot as getGraph (prototype {@code _issue_refs}):
 * the company's INVOLVES issues and its STRUCTURALLY_RELATED_TO issues, newest first, each with its edge role,
 * evidence count and structural basis. The snapshot holds no AI company summary, so {@code summary} stays absent.
 */
@Component
public class GraphCompanySnapshotReader implements CompanyGraphSnapshotReader {
    private final PublicGraphReader reader;

    public GraphCompanySnapshotReader(PublicGraphReader reader) {
        this.reader = reader;
    }

    @Override
    public Optional<CompanyGraphSnapshot> read(CompanyGraphReadRequest request) {
        PublicGraphReader.Pinned pinned;
        try {
            pinned = reader.read(request.round(), request.graphVersion(), request.asOf());
        } catch (CustomException exception) {
            // No public version yet and no selector asked for one: the sections are unavailable, the profile is not.
            boolean selectors = request.round() != null || request.graphVersion() != null || request.asOf() != null;
            if (exception.getErrorCode() == ErrorCode.VERSION_UNAVAILABLE && !selectors) return Optional.empty();
            throw exception;
        }
        DisplayGraph graph = pinned.graph();
        String companyId = request.companyId();
        Map<String, Relation> relations = graph.snapshot.relations().stream()
                .collect(Collectors.toMap(Relation::relationId, Function.identity()));
        Map<String, Article> articles = graph.snapshot.articles().stream()
                .collect(Collectors.toMap(a -> a.articleId() + "@" + a.version(), Function.identity()));
        return Optional.of(new CompanyGraphSnapshot(pinned.selected().version().id(), pinned.selected().asOf(),
                graph.companies.containsKey(companyId),
                issues(graph, companyId, "INVOLVES", relations, articles),
                issues(graph, companyId, "STRUCTURALLY_RELATED_TO", relations, articles), null));
    }

    private static List<CompanyIssueRef> issues(DisplayGraph graph, String companyId, String relationType,
            Map<String, Relation> relations, Map<String, Article> articles) {
        return graph.edges.values().stream()
                .filter(e -> !e.derived() && e.target().equals(companyId) && e.relationType().equals(relationType))
                .sorted(Comparator.comparing(e -> graph.issues.get(e.source()), DisplayGraph.RECENT))
                .map(e -> {
                    var issue = graph.issues.get(e.source());
                    List<BasisOut> basis = e.relationIds().stream().map(relations::get)
                            .flatMap(r -> r.basis().stream()).map(b -> basisOut(b, articles)).toList();
                    return new CompanyIssueRef(issue.label(), issue.issueId(), issue.eventTime(), issue.timePrecision(),
                            e.role(), e.assertionStatus(), e.evidenceIds().size(), basis);
                })
                .toList();
    }

    /** sourceUrl only when the cited article version is still visible in this read (asOf, current exclusions). */
    static BasisOut basisOut(Basis b, Map<String, Article> visibleArticles) {
        Article article = b.articleId() == null ? null : visibleArticles.get(b.articleId() + "@" + b.articleVersion());
        return new BasisOut(b.basisId(), b.relationType(), article == null ? null : article.url(),
                Instant.parse(b.verifiedAt()), b.validFrom(), b.validUntil(), b.countries());
    }
}
