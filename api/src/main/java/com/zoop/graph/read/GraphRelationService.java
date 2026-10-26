package com.zoop.graph.read;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.response.Metadata;
import com.zoop.common.response.SectionFailure;
import com.zoop.graph.read.dto.EdgeDetail;
import com.zoop.graph.read.dto.EdgeDetail.EndpointRef;
import com.zoop.graph.read.dto.EdgeDetail.Verification;
import com.zoop.graph.read.dto.EdgeDetail.ViaIssue;
import com.zoop.graph.read.dto.StructuralDetails;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Article;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Relation;
import java.time.Instant;
import java.time.format.DateTimeParseException;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.function.Function;
import java.util.stream.Collectors;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Service;

/**
 * {@code getCompanyRelation}: one display edge of the pinned, filtered graph (prototype {@code edge_detail}), with the
 * source relations behind it. An edge that is not visible in that read (another version, before asOf, withdrawn
 * today) is 404, never looked up in a newer graph.
 */
@Service
public class GraphRelationService {
    private static final Logger log = LoggerFactory.getLogger(GraphRelationService.class);
    static final String DERIVED_EXPLANATION = "두 기업이 같은 사건에 함께 등장했다는 뜻이에요. 직접 거래나 영향 관계는 아니에요.";
    static final Map<String, String> EXPLANATIONS = Map.of(
            "INVOLVES", "기사에 이 기업의 역할이 직접 적혀 있어요.",
            "STRUCTURALLY_RELATED_TO", "공급·생산 같은 사업 관계로 이 사건과 이어져 있어요. 직접 참여했다는 뜻은 아니에요.",
            "FOLLOWS", "앞 사건에 이어 일어난 사건이에요.");

    private final PublicGraphReader reader;
    private final NamedParameterJdbcTemplate jdbc;
    private final GraphStructuralDetailReader structuralDetails;

    public GraphRelationService(PublicGraphReader reader, NamedParameterJdbcTemplate jdbc, GraphStructuralDetailReader structuralDetails) {
        this.reader = reader;
        this.jdbc = jdbc;
        this.structuralDetails = structuralDetails;
    }

    public EdgeDetail getRelation(String edgeId, String round, String graphVersion, String asOf, String requestId) {
        PublicGraphReader.Pinned pinned = reader.read(round, graphVersion, parseInstant(asOf));
        DisplayGraph graph = pinned.graph();
        DisplayGraph.Edge edge = graph.edges.get(edgeId);
        if (edge == null) throw new CustomException(ErrorCode.RESOURCE_NOT_FOUND);

        Map<String, Relation> relations = graph.snapshot.relations().stream()
                .collect(Collectors.toMap(Relation::relationId, Function.identity()));
        Map<String, Article> articles = graph.snapshot.articles().stream()
                .collect(Collectors.toMap(a -> a.articleId() + "@" + a.version(), Function.identity()));
        List<Relation> sources = edge.relationIds().stream().map(relations::get).toList();
        Map<String, PublicGraphSnapshot.Company> catalog = CompanyAppearance.of(jdbc,
                List.of(edge.source(), edge.target()).stream().filter(graph.companies::containsKey).toList());
        StructuralDetails structural;
        boolean retryableStructuralFailure = false;
        try {
            structural = structuralDetails.read(pinned, edge, round, requestId);
        } catch (CustomException failure) {
            if (failure.getErrorCode() != ErrorCode.SOURCE_UNAVAILABLE) throw failure;
            retryableStructuralFailure = failure.isRetryable();
            log.warn("Structural relation detail is unavailable (graphVersion={}, edgeId={}, retryable={}, requestId={})",
                    pinned.selected().version().id(), edge.id(), retryableStructuralFailure, requestId);
            structural = StructuralDetails.unavailable("details_not_available");
        }
        boolean partial = "unavailable".equals(structural.status())
                && "details_not_available".equals(structural.reason());
        Metadata metadata = new Metadata(pinned.selected().source(), pinned.selected().asOf(),
                pinned.selected().version().id(), requestId, partial,
                partial ? List.of(new SectionFailure("structuralDetails",
                        retryableStructuralFailure ? "SOURCE_UNAVAILABLE" : "STRUCTURAL_DETAIL_UNAVAILABLE",
                        "사업 관계 상세 정보를 제공할 수 없습니다.", retryableStructuralFailure, pinned.selected().asOf())) : List.of());
        return new EdgeDetail(edge.id(), edge.relationType(), edge.derived(), !edge.derived(),
                endpoint(graph, catalog, edge.source()), endpoint(graph, catalog, edge.target()), edge.role(), edge.summary(),
                sources.stream().map(Relation::role).filter(Objects::nonNull).map(RoleLabels::display).distinct().toList(),
                edge.assertionStatus(), edge.evidenceIds(),
                sources.stream().flatMap(r -> r.basis().stream())
                        .map(b -> GraphCompanySnapshotReader.basisOut(b, articles, pinned.selected().asOf())).toList(),
                edge.relationIds(),
                edge.derived() ? new Verification("not_applicable", "파생 연결은 검증 대상이 아닙니다.")
                        : pinned.selected().reconstructed()
                                ? new Verification("not_applicable", "저장된 브리핑 연결의 재구성이며 별도 관계 승인이나 역할 확인을 뜻하지 않습니다.")
                                : new Verification("ALLOW", null),
                edge.derived() ? via(graph, edge) : List.of(),
                edge.derived() ? DERIVED_EXPLANATION
                        : "INVOLVES".equals(edge.relationType()) && (pinned.selected().reconstructed() || edge.role() == null)
                                ? (pinned.selected().briefing() != null ? "이 회차에 저장된" : "저장된")
                                        + " 기업·사건 연결입니다. 구체적인 역할은 저장된 근거에서 확인해야 합니다."
                                : EXPLANATIONS.get(edge.relationType()),
                RelationValidity.of(graph.basesOf(edge), pinned.selected().asOf()), structural, metadata);
    }

    /** For a derived edge: each shared issue with the evidence on its links to the two companies. */
    private static List<ViaIssue> via(DisplayGraph graph, DisplayGraph.Edge edge) {
        return edge.via().stream().map(graph.issues::get).map(issue -> new ViaIssue(issue.label(), issue.issueId(),
                issue.eventTime(), issue.timePrecision(), graph.edges.values().stream()
                        .filter(e -> !e.derived() && e.source().equals(issue.issueId())
                                && DisplayGraph.COMPANY_LINKS.contains(e.relationType())
                                && (e.target().equals(edge.source()) || e.target().equals(edge.target())))
                        .flatMap(e -> e.evidenceIds().stream()).distinct().toList()))
                .toList();
    }

    /** A company end carries its logo and brand colour (snapshot first, then the catalog); an issue end has none. */
    private static EndpointRef endpoint(DisplayGraph graph, Map<String, PublicGraphSnapshot.Company> catalog, String id) {
        var issue = graph.issues.get(id);
        if (issue != null) return new EndpointRef(id, "issue", issue.label(), null, null);
        var company = CompanyAppearance.fill(graph.companies.get(id), catalog.get(id));
        return new EndpointRef(id, "company", company.label(), company.logoUrl(), company.brandColor());
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
