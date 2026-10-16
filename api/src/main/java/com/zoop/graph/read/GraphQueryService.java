package com.zoop.graph.read;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.graph.read.GraphSelection.Kind;
import com.zoop.graph.read.dto.GraphResponse;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Company;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Issue;
import com.zoop.graph.version.SelectedGraphVersion;
import java.time.Instant;
import java.time.format.DateTimeParseException;
import java.util.List;
import java.util.Map;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Service;

/**
 * {@code getGraph} and {@code getCompanyGraphAsOf}: one pinned version read through {@link PublicGraphReader}, then
 * the display edges and the node selection. Errors are never turned into an empty graph.
 */
@Service
public class GraphQueryService {
    /** Node cap recorded in metadata.limit (prototype value; revisit after measuring real snapshot sizes). */
    static final int NODE_LIMIT = 500;

    private final PublicGraphReader reader;
    private final NamedParameterJdbcTemplate jdbc;

    public GraphQueryService(PublicGraphReader reader, NamedParameterJdbcTemplate jdbc) {
        this.reader = reader;
        this.jdbc = jdbc;
    }

    public GraphResponse getGraph(String mode, String companyId, Integer depth, String round, String graphVersion,
            String asOf, String requestId) {
        String resolvedMode = mode == null ? "all" : mode;
        if (!resolvedMode.equals("all") && !resolvedMode.equals("personal")) throw invalid();
        if (depth != null && depth < 1) throw invalid();
        Instant requestedAsOf = parseInstant(asOf);
        if (resolvedMode.equals("personal")) {
            // shortcut: personal mode needs the member holdings/watchlist read contract (#60); until it exists the
            // personal source is reported unavailable instead of returning a public graph as if it were personal.
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        }
        List<String> focus = companyId == null ? List.of() : List.of(companyId);
        Map<String, Company> catalog = catalogCompanies(focus);

        PublicGraphReader.Pinned pinned = reader.read(round, graphVersion, requestedAsOf);
        GraphSelection.Result selection = GraphSelection.select(pinned.graph(), focus, depth, NODE_LIMIT);
        return response(pinned, selection, catalog, focus, resolvedMode, depth, requestId);
    }

    /** Company timeline graph: asOf is required with an explicit offset, depth counts literal edges (1 or 2). */
    public GraphResponse getCompanyGraphAsOf(String companyId, String asOf, Integer depth, String graphVersion,
            String requestId) {
        if (asOf == null || asOf.isBlank()) throw invalid();
        int hops = depth == null ? 1 : depth;
        if (hops < 1 || hops > 2) throw invalid();
        Instant at = parseInstant(asOf);
        List<String> focus = List.of(companyId);
        Map<String, Company> catalog = catalogCompanies(focus);

        PublicGraphReader.Pinned pinned = reader.read(null, graphVersion, at);
        // Two company hops always cover two literal edges; the literal walk then trims to the requested depth.
        GraphSelection.Result ego = GraphSelection.select(pinned.graph(), focus, 2, NODE_LIMIT);
        GraphSelection.Result selection = GraphSelection.neighbourhood(pinned.graph(), ego, companyId, hops);
        return response(pinned, selection, catalog, focus, "all", hops, requestId);
    }

    private static GraphResponse response(PublicGraphReader.Pinned pinned, GraphSelection.Result selection,
            Map<String, Company> catalog, List<String> focus, String mode, Integer depth, String requestId) {
        DisplayGraph graph = pinned.graph();
        SelectedGraphVersion selected = pinned.selected();
        Map<String, Kind> picked = selection.nodes();
        List<GraphResponse.Node> nodes = picked.entrySet().stream()
                .map(e -> e.getValue() == Kind.ISSUE ? issueNode(graph.issues.get(e.getKey()))
                        : companyNode(graph.companies.getOrDefault(e.getKey(), catalog.get(e.getKey())), focus.contains(e.getKey())))
                .toList();
        List<GraphResponse.Edge> edges = graph.edges.values().stream()
                .filter(e -> picked.containsKey(e.source()) && picked.containsKey(e.target()))
                .filter(e -> !e.derived() || e.via().stream().anyMatch(picked::containsKey))
                .map(e -> new GraphResponse.Edge(e.id(), e.source(), e.target(), e.relationType(), e.role(), e.summary(),
                        e.assertionStatus(), e.derived(), e.via(), e.evidenceIds()))
                .toList();
        String emptyReason = edges.isEmpty() ? (focus.isEmpty() ? "no_approved_issues" : "no_related_issues") : null;
        return new GraphResponse(nodes, edges, new GraphResponse.Metadata("public_graph_snapshot",
                selected.asOf().toString(), selected.version().id(), mode, selection.truncated(), emptyReason,
                focus, depth, NODE_LIMIT, requestId, false, List.of(), null));
    }

    /** Focus companies must exist in the catalog; one missing from the version still appears with no relations. */
    private Map<String, Company> catalogCompanies(List<String> ids) {
        if (ids.isEmpty()) return Map.of();
        Map<String, Company> found = new java.util.HashMap<>();
        jdbc.query("SELECT id, name, brand_color, logo_url FROM companies WHERE id IN (:ids)",
                new MapSqlParameterSource("ids", ids), (rs, n) -> new Company(rs.getString("id"),
                        rs.getString("name"), rs.getString("brand_color"), rs.getString("logo_url")))
                .forEach(c -> found.put(c.companyId(), c));
        if (!found.keySet().containsAll(ids)) throw new CustomException(ErrorCode.RESOURCE_NOT_FOUND);
        return found;
    }

    private static GraphResponse.Node companyNode(Company c, boolean focus) {
        return new GraphResponse.Node(c.companyId(), "company", c.label(), focus, false, false, c.brandColor(),
                c.logoUrl(), null, null, null, null, null, null);
    }

    private static GraphResponse.Node issueNode(Issue i) {
        return new GraphResponse.Node(i.issueId(), "issue", i.label(), false, false, false, null, null, i.eventTime(),
                i.timePrecision(), i.action(), i.target(), i.evidenceIds().size(), i.geography());
    }

    private static Instant parseInstant(String value) {
        if (value == null || value.isBlank()) return null;
        try {
            return Instant.parse(value);
        } catch (DateTimeParseException exception) {
            throw new CustomException(ErrorCode.INVALID_REQUEST, exception);
        }
    }

    private static CustomException invalid() {
        return new CustomException(ErrorCode.INVALID_REQUEST);
    }
}
