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
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Service;

/**
 * {@code getGraph} (all and personal) and {@code getCompanyGraphAsOf}: one pinned version read through {@link PublicGraphReader}, then
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

    /**
     * personal is the member's own companies, read by the caller after authentication; null in all mode. Personal
     * mode centres on them (or on companyId) and marks holding/watch; all mode carries no personal data.
     */
    public GraphResponse getGraph(String mode, String companyId, Integer depth, String round, String graphVersion,
            String asOf, String personalFilter, PersonalCompanies.Ids personal, String requestId) {
        String resolvedMode = mode == null ? "all" : mode;
        if (!resolvedMode.equals("all") && !resolvedMode.equals("personal")) throw invalid();
        if (depth != null && depth < 1) throw invalid();
        Instant requestedAsOf = parseInstant(asOf);
        boolean isPersonal = resolvedMode.equals("personal");
        // personalFilter applies to personal mode only; all mode ignores it (contract).
        String filter = personalFilter == null ? "all" : personalFilter;
        if (isPersonal && !List.of("all", "holdings", "watchlist").contains(filter)) throw invalid();
        if (isPersonal && personal == null) throw new IllegalStateException("personal mode without the member companies");
        // A briefing round is a market-wide snapshot (prototype round_all_only).
        if (isPersonal && round != null) throw invalid();

        Map<String, Company> catalog = new HashMap<>(catalogCompanies(companyId == null ? List.of() : List.of(companyId)));
        List<String> focus;
        if (!isPersonal) {
            focus = companyId == null ? List.of() : List.of(companyId);
        } else {
            List<String> own = catalogKnown(personal.select(filter), catalog);
            focus = companyId != null ? List.of(companyId) : own;
        }

        PublicGraphReader.Pinned pinned = reader.read(round, graphVersion, requestedAsOf);
        // No own companies: an empty personal graph, never the whole market presented as personal.
        GraphSelection.Result selection = isPersonal && focus.isEmpty()
                ? new GraphSelection.Result(Map.of(), false)
                : GraphSelection.select(pinned.graph(), focus, depth, NODE_LIMIT);
        GraphResponse response = response(pinned, selection, catalog, focus, resolvedMode, depth, requestId,
                isPersonal ? personal : null, isPersonal ? filter : null);
        if (isPersonal && focus.isEmpty()) {
            return new GraphResponse(response.nodes(), response.edges(),
                    withEmptyReason(response.metadata(), "no_personal_stocks"));
        }
        return response;
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
        return response(pinned, selection, catalog, focus, "all", hops, requestId, null, null);
    }

    private static GraphResponse response(PublicGraphReader.Pinned pinned, GraphSelection.Result selection,
            Map<String, Company> catalog, List<String> focus, String mode, Integer depth, String requestId,
            PersonalCompanies.Ids personal, String personalFilter) {
        DisplayGraph graph = pinned.graph();
        SelectedGraphVersion selected = pinned.selected();
        Map<String, Kind> picked = selection.nodes();
        List<GraphResponse.Node> nodes = picked.entrySet().stream()
                .map(e -> e.getValue() == Kind.ISSUE ? issueNode(graph.issues.get(e.getKey()))
                        : companyNode(graph.companies.getOrDefault(e.getKey(), catalog.get(e.getKey())), focus.contains(e.getKey()), personal))
                .toList();
        List<GraphResponse.Edge> edges = graph.edges.values().stream()
                .filter(e -> picked.containsKey(e.source()) && picked.containsKey(e.target()))
                .filter(e -> !e.derived() || e.via().stream().anyMatch(picked::containsKey))
                .map(e -> new GraphResponse.Edge(e.id(), e.source(), e.target(), e.relationType(), e.role(), e.summary(),
                        e.assertionStatus(), e.derived(), e.via(), e.evidenceIds(),
                        RelationValidity.of(graph.basesOf(e), selected.asOf())))
                .toList();
        String emptyReason = edges.isEmpty() ? (focus.isEmpty() ? "no_approved_issues" : "no_related_issues") : null;
        return new GraphResponse(nodes, edges, new GraphResponse.Metadata("public_graph_snapshot",
                selected.asOf().toString(), selected.version().id(), mode, selection.truncated(), emptyReason,
                focus, depth, NODE_LIMIT, requestId, false, List.of(), personalFilter));
    }

    private static GraphResponse.Metadata withEmptyReason(GraphResponse.Metadata m, String emptyReason) {
        return new GraphResponse.Metadata(m.source(), m.asOf(), m.graphVersion(), m.mode(), m.truncated(), emptyReason,
                m.focusCompanyIds(), m.depth(), m.limit(), m.requestId(), m.partial(), m.failures(), m.personalFilter());
    }

    /** Focus companies must exist in the catalog; one missing from the version still appears with no relations. */
    private Map<String, Company> catalogCompanies(List<String> ids) {
        if (ids.isEmpty()) return Map.of();
        Map<String, Company> found = new HashMap<>();
        jdbc.query("SELECT id, name, brand_color, logo_url FROM companies WHERE id IN (:ids)",
                new MapSqlParameterSource("ids", ids), (rs, n) -> new Company(rs.getString("id"),
                        rs.getString("name"), rs.getString("brand_color"), rs.getString("logo_url")))
                .forEach(c -> found.put(c.companyId(), c));
        if (!found.keySet().containsAll(ids)) throw new CustomException(ErrorCode.RESOURCE_NOT_FOUND);
        return found;
    }

    /** The member's companies that the catalog knows; a stale id is left out instead of failing the whole graph. */
    private List<String> catalogKnown(List<String> ids, Map<String, Company> catalog) {
        if (ids.isEmpty()) return List.of();
        jdbc.query("SELECT id, name, brand_color, logo_url FROM companies WHERE id IN (:ids)",
                new MapSqlParameterSource("ids", ids), (rs, n) -> new Company(rs.getString("id"),
                        rs.getString("name"), rs.getString("brand_color"), rs.getString("logo_url")))
                .forEach(c -> catalog.put(c.companyId(), c));
        return ids.stream().filter(catalog::containsKey).toList();
    }

    private static GraphResponse.Node companyNode(Company c, boolean focus, PersonalCompanies.Ids personal) {
        boolean holding = personal != null && personal.holdings().contains(c.companyId());
        boolean watch = personal != null && personal.watchlist().contains(c.companyId());
        return new GraphResponse.Node(c.companyId(), "company", c.label(), focus, holding, watch, c.brandColor(),
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
