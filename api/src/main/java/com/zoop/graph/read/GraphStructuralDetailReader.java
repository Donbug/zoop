package com.zoop.graph.read;

import com.zoop.common.json.StrictJson;
import com.zoop.common.json.StrictJson.Obj;
import com.zoop.document.evidence.service.EvidenceService;
import com.zoop.graph.read.dto.StructuralDetails;
import com.zoop.graph.read.dto.StructuralDetails.Company;
import com.zoop.graph.read.dto.StructuralDetails.Link;
import com.zoop.graph.read.dto.StructuralDetails.Path;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Basis;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Evidence;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Relation;
import java.time.DateTimeException;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.function.Predicate;
import java.util.stream.Collectors;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

/**
 * FS023 / D-GRP-04. Reads only the pinned import receipt; never AI storage or a newer graph.
 * The whole structural section is withheld if any constituent path cannot be shown intact.
 * pathCompanies remain private support references, including their identifiers and labels.
 */
@Component
public class GraphStructuralDetailReader {
    private static final Logger log = LoggerFactory.getLogger(GraphStructuralDetailReader.class);
    private static final Set<String> SUPPORTED = Set.of("zoop-graph-handoff-bundle-5",
            "zoop-graph-handoff-bundle-6", "zoop-graph-handoff-bundle-7", "zoop-graph-handoff-bundle-8",
            "zoop-graph-handoff-bundle-9");
    private static final Set<String> LEGACY = Set.of("zoop-graph-handoff-bundle-1",
            "zoop-graph-handoff-bundle-2", "zoop-graph-handoff-bundle-3", "zoop-graph-handoff-bundle-4");
    private final EvidenceService evidence;

    public GraphStructuralDetailReader(EvidenceService evidence) { this.evidence = evidence; }

    public StructuralDetails read(PublicGraphReader.Pinned pinned, DisplayGraph.Edge edge, String round, String requestId) {
        if (!"STRUCTURALLY_RELATED_TO".equals(edge.relationType())) return StructuralDetails.notApplicable();
        if (pinned.selected().reconstructed() || !"snapshot".equals(pinned.selected().version().kind()))
            return StructuralDetails.unavailable("not_recorded");
        try {
            return imported(pinned, edge, round, requestId);
        } catch (StrictJson.Malformed | DateTimeException malformed) {
            log.warn("Structural relation receipt details are malformed (graphVersion={}, edgeId={}, requestId={})",
                    pinned.selected().version().id(), edge.id(), requestId);
            return StructuralDetails.unavailable("details_not_available");
        }
    }

    private StructuralDetails imported(PublicGraphReader.Pinned pinned, DisplayGraph.Edge edge, String round, String requestId) {
        String version = pinned.selected().version().id();
        var publication = evidence.graphPublication(version, requestId);
        DisplayGraph graph = pinned.graph();
        Map<String, Relation> snapshotRelations = new HashMap<>();
        Map<String, Evidence> snapshotEvidence = new HashMap<>();
        Map<RelationEndpoints, List<Relation>> involvesByEndpoints = new HashMap<>();
        for (Relation relation : graph.snapshot.relations()) {
            require(snapshotRelations.putIfAbsent(relation.relationId(), relation) == null);
            if ("INVOLVES".equals(relation.relationType())) {
                involvesByEndpoints.computeIfAbsent(new RelationEndpoints(relation.source(), relation.target()),
                        ignored -> new ArrayList<>()).add(relation);
            }
        }
        for (Evidence item : graph.snapshot.evidence()) require(snapshotEvidence.putIfAbsent(item.evidenceId(), item) == null);
        Map<String, Boolean> checked = new HashMap<>();
        Instant at = pinned.selected().asOfRequested() ? pinned.selected().asOf() : null;
        Set<String> visibleEvidence = snapshotEvidence.keySet();
        Predicate<String> shown = id -> visibleEvidence.contains(id) && checked.computeIfAbsent(id,
                key -> evidence.shownNow(key, round, version, at, requestId));
        List<Path> result = new ArrayList<>();
        boolean available = true;
        for (String relationId : edge.relationIds().stream().sorted().toList()) {
            var owners = publication.relationSources().get(relationId);
            require(owners != null && owners.publicSource().equals(edge.source()) && owners.publicTarget().equals(edge.target()));
            for (var owner : publication.selectedRelationSources(relationId)) {
                var contribution = publication.source(owner.sourceVersionId());
                Obj bundle = contribution.bundle();
                String schema = bundle.string("schemaVersion");
                if ("legacy-real".equals(contribution.sourceKind())) return StructuralDetails.unavailable("not_recorded");
                if (LEGACY.contains(schema)) return StructuralDetails.unavailable("legacy_data");
                require(SUPPORTED.contains(schema));
                Map<String, Obj> relations = index(bundle.objects("relations"), "id");
                Map<String, Obj> spans = index(bundle.objects("evidence"), "id");
                Map<String, Obj> publicCompanies = index(bundle.objects("companies"), "id");
                Map<String, Obj> privateCompanies = index(bundle.objects("pathCompanies"), "id");
                var original = contribution.projection().relations().stream()
                        .filter(r -> r.relationId().equals(owner.relationId())).findFirst().orElseThrow(StrictJson.Malformed::new);
                Obj relation = relations.get(owner.relationId());
                require(relation != null && relation.string("type").equals(edge.relationType())
                        && relation.string("source").equals(original.source()) && relation.string("target").equals(original.target())
                        && publication.publicIssue(contribution.issueRef(original.source())).equals(edge.source())
                        && original.target().equals(edge.target()));
                var visibleRelation = snapshotRelations.get(relationId);
                require(visibleRelation != null);
                List<Obj> bases = relation.objects("basis");
                require(bases.size() >= 1 && bases.size() <= 2);
                Map<String, Obj> baseIndex = index(bases, "relationKey");
                require(visibleRelation.basis().stream().allMatch(b -> baseIndex.containsKey(b.basisId())));
                // A later basis removed by asOf must not be recovered via a different readable citation.
                boolean pathVisible = bases.size() == visibleRelation.basis().size();
                Map<String, Basis> visibleBases = new HashMap<>();
                visibleRelation.basis().forEach(b -> visibleBases.put(b.basisId(), b));
                Obj path = relation.object("structuralPath");
                if ("unavailable".equals(path.string("status"))) {
                    path.exactly(Set.of("status", "reason"));
                    require(bases.size() == 2 && "intermediate_company_unmapped".equals(path.string("reason")));
                    log.info("Structural relation path withheld by producer mapping (graphVersion={}, edgeId={}, reason=intermediate_company_unmapped, requestId={})",
                            version, edge.id(), requestId);
                    available = false;
                    continue;
                }
                path.exactly(Set.of("status", "companyIds", "links"));
                require("complete".equals(path.string("status")));
                List<String> ids = path.strings("companyIds");
                List<Obj> links = path.objects("links");
                require(ids.size() == bases.size() + 1 && new HashSet<>(ids).size() == ids.size()
                        && links.size() == bases.size() && ids.getLast().equals(edge.target()));
                for (String id : ids) {
                    require(publicCompanies.containsKey(id) || privateCompanies.containsKey(id));
                    pathVisible &= publicCompanies.containsKey(id) && !privateCompanies.containsKey(id)
                            && graph.companies.containsKey(id);
                }
                // The participating link must belong to this original source and remain visible after mapping.
                boolean participantVisible = involvesByEndpoints
                        .getOrDefault(new RelationEndpoints(edge.source(), ids.getFirst()), List.of()).stream()
                        .filter(r -> !r.evidenceIds().isEmpty() && r.evidenceIds().stream().allMatch(shown))
                        .anyMatch(r -> publication.selectedRelationSources(r.relationId()).stream()
                                .filter(ref -> ref.sourceVersionId().equals(contribution.sourceVersionId()))
                                .anyMatch(ref -> contribution.projection().relations().stream().anyMatch(local ->
                                        local.relationId().equals(ref.relationId()) && "INVOLVES".equals(local.relationType())
                                                && original.source().equals(local.source()) && ids.getFirst().equals(local.target())
                                                && !local.evidenceIds().isEmpty() && local.evidenceIds().stream().allMatch(shown))));
                pathVisible &= participantVisible;
                List<Link> outputLinks = new ArrayList<>();
                for (int i = 0; i < bases.size(); i++) {
                    Obj b = bases.get(i);
                    Obj link = links.get(i).exactly(Set.of("supplierCompanyId", "customerCompanyId"));
                    String supplier = link.string("supplierCompanyId"), customer = link.string("customerCompanyId");
                    require(!supplier.equals(customer) && Set.of(supplier, customer).equals(Set.of(ids.get(i), ids.get(i + 1))));
                    String basisId = b.string("relationKey");
                    require("SUPPLIES".equals(b.string("relationType")));
                    String business = scope(b, "businessScope"), product = scope(b, "productScope");
                    List<String> citations = b.strings("evidenceIds");
                    require(!citations.isEmpty() && new HashSet<>(citations).size() == citations.size());
                    Basis visible = visibleBases.get(basisId);
                    if (visible == null) { pathVisible = false; continue; }
                    require(visible.relationType().equals(b.string("relationType"))
                            && visible.verifiedAt().equals(instantText(b.string("verifiedAt")))
                            && Objects.equals(visible.validFrom(), b.stringOrNull("validFrom"))
                            && Objects.equals(visible.validUntil(), b.stringOrNull("validUntil"))
                            && visible.countries().equals(b.strings("countries")));
                    Set<String> articleKeys = new HashSet<>();
                    b.objects("sourceArticles").forEach(a -> require(articleKeys.add(articleKey(a))));
                    require(articleKeys.equals(visible.articles().stream()
                            .map(a -> a.articleId() + "@" + a.articleVersion()).collect(Collectors.toSet())));
                    Set<String> citedArticles = new HashSet<>();
                    for (String id : citations) {
                        Obj span = spans.get(id);
                        require(span != null);
                        citedArticles.add(articleKey(span));
                        Evidence inSnapshot = snapshotEvidence.get(id);
                        if (inSnapshot != null) require(articleKey(span).equals(
                                inSnapshot.articleId() + "@" + inSnapshot.articleVersion()));
                        pathVisible &= shown.test(id);
                    }
                    require(citedArticles.equals(articleKeys));
                    outputLinks.add(new Link(basisId, "SUPPLIES", supplier, customer, business, product,
                            visible.validFrom(), visible.validUntil(), RelationValidity.of(visible, pinned.selected().asOf()),
                            Instant.parse(visible.verifiedAt()), visible.countries(), citations));
                }
                if (pathVisible) result.add(new Path(relationId, ids.stream()
                        .map(id -> new Company(id, graph.companies.get(id).label())).toList(), outputLinks));
                available &= pathVisible;
            }
        }
        require(!edge.relationIds().isEmpty());
        return available ? new StructuralDetails("available", null, result.stream().distinct().toList())
                : StructuralDetails.unavailable("details_not_available");
    }

    private static Map<String, Obj> index(List<Obj> rows, String key) {
        Map<String, Obj> result = new HashMap<>();
        for (Obj row : rows) require(result.putIfAbsent(row.string(key), row) == null);
        return result;
    }
    private record RelationEndpoints(String source, String target) { }
    private static String articleKey(Obj article) { return article.string("articleId") + "@" + article.string("articleVersion"); }
    private static String instantText(String value) { return OffsetDateTime.parse(value).toInstant().toString(); }
    private static String scope(Obj basis, String key) {
        String value = basis.stringOrNull(key);
        require(value == null || value.codePointCount(0, value.length()) <= 500);
        return value;
    }
    private static void require(boolean condition) { if (!condition) throw new StrictJson.Malformed(); }
}
