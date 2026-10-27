package com.zoop.graph.read;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.json.StrictJson;
import com.zoop.common.json.StrictJson.Obj;
import com.zoop.common.response.Metadata;
import com.zoop.document.evidence.service.EvidenceService;
import com.zoop.graph.read.dto.CompanyIssueImpactResponse;
import com.zoop.graph.read.dto.CompanyIssueImpactResponse.BusinessLink;
import com.zoop.graph.read.dto.CompanyIssueImpactResponse.BusinessPath;
import com.zoop.graph.read.dto.CompanyIssueImpactResponse.Impact;
import com.zoop.graph.read.dto.CompanyIssueImpactResponse.Step;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Basis;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Relation;
import java.time.Instant;
import java.time.format.DateTimeParseException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Comparator;
import java.util.HexFormat;
import java.util.HashSet;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;
import org.springframework.stereotype.Service;

/** Reads one company's visible relationship to an issue from a single pinned public graph. */
@Service
public class CompanyIssueImpactService {
    private final PublicGraphReader reader;
    private final EvidenceService evidence;

    public CompanyIssueImpactService(PublicGraphReader reader, EvidenceService evidence) {
        this.reader = reader;
        this.evidence = evidence;
    }

    public CompanyIssueImpactResponse getImpactPath(String companyId, String issueId, String round,
            String graphVersion, String asOf, String requestId) {
        Instant requestedAsOf = parseInstant(asOf);
        PublicGraphReader.Pinned pinned = reader.read(round, graphVersion, requestedAsOf, requestId);
        DisplayGraph graph = pinned.graph();
        if (!graph.companies.containsKey(companyId) || !graph.issues.containsKey(issueId)) {
            throw new CustomException(ErrorCode.RESOURCE_NOT_FOUND);
        }

        DisplayGraph.Edge selected = graph.edges.values().stream()
                .filter(edge -> !edge.derived() && edge.source().equals(issueId) && edge.target().equals(companyId))
                .filter(edge -> "INVOLVES".equals(edge.relationType()))
                .min(Comparator.comparing(DisplayGraph.Edge::id))
                .orElseGet(() -> graph.edges.values().stream()
                        .filter(edge -> !edge.derived() && edge.source().equals(issueId) && edge.target().equals(companyId))
                        .filter(edge -> "STRUCTURALLY_RELATED_TO".equals(edge.relationType()))
                        .min(Comparator.comparing(DisplayGraph.Edge::id)).orElse(null));

        Metadata metadata = new Metadata(pinned.selected().source(), pinned.selected().asOf(),
                pinned.selected().version().id(), requestId, false, List.of());
        if (selected == null) {
            return new CompanyIssueImpactResponse(companyId, issueId, "none", null, null, List.of(), null,
                    new Impact("unavailable", "no_public_path", List.of()), metadata);
        }

        boolean direct = "INVOLVES".equals(selected.relationType());
        String reason = direct ? "기사에 이 기업의 역할이 직접 적혀 있어요."
                : "공개 사업 관계로 이 이슈와 연결된 기업이에요.";
        List<String> evidenceIds = selected.evidenceIds();
        List<Step> steps = List.of(new Step(issueId, "issue", reason, evidenceIds),
                new Step(companyId, "company", selected.summary(), evidenceIds));
        BusinessPath businessPath = direct ? null
                : businessPath(pinned, selected, issueId, round, graphVersion, requestedAsOf, requestId);
        Impact impact = direct ? impact(pinned, selected, issueId, companyId, round, graphVersion, requestedAsOf, requestId)
                : new Impact("unavailable", "issue_impact_not_produced", List.of());
        return new CompanyIssueImpactResponse(companyId, issueId, "available", direct ? "direct" : "structural",
                selected.id(), steps, businessPath, impact, metadata);
    }

    /** Exposes only the independently verified per-source rows tied to this visible INVOLVES edge. */
    private Impact impact(PublicGraphReader.Pinned pinned, DisplayGraph.Edge edge, String issueId, String companyId,
            String round, String graphVersion, Instant requestedAsOf, String requestId) {
        try {
            return readImpact(pinned, edge, issueId, companyId, round, graphVersion, requestedAsOf, requestId);
        } catch (StrictJson.Malformed malformed) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, malformed);
        }
    }

    private Impact readImpact(PublicGraphReader.Pinned pinned, DisplayGraph.Edge edge, String issueId, String companyId,
            String round, String graphVersion, Instant requestedAsOf, String requestId) {
        if (!receiptBacked(pinned)) return new Impact("unavailable", "not_recorded", List.of());
        Obj bundle = evidence.graphImportBundle(pinned.selected().version().id(), requestId);
        if (!bundle.has("impacts")) return new Impact("unavailable", "not_recorded", List.of());

        Map<String, List<Obj>> rowsByRelation = new java.util.HashMap<>();
        for (Obj row : bundle.objects("impacts")) {
            row.exactly(IMPACT_ROW_KEYS);
            rowsByRelation.computeIfAbsent(row.string("edgeId"), ignored -> new java.util.ArrayList<>()).add(row);
        }
        Map<String, Obj> receiptRelations = index(bundle.objects("relations"), "id");
        List<ImpactCandidate> verified = new java.util.ArrayList<>();
        boolean evidenceUnavailable = false;
        String evidenceGraphVersion = round == null ? pinned.selected().version().id() : graphVersion;

        for (String relationId : edge.relationIds()) {
            Obj relation = receiptRelations.get(relationId);
            if (relation == null) throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
            if (!"INVOLVES".equals(relation.string("type")) || !issueId.equals(relation.string("source"))
                    || !companyId.equals(relation.string("target"))) throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);

            Set<String> sourceRefs = new HashSet<>();
            for (Obj sourceRef : relation.objects("sourceRefs")) {
                sourceRef.exactly(Set.of("kind", "jobId", "id"));
                if (!"s3-relation".equals(sourceRef.string("kind"))) {
                    throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
                }
                sourceRefs.add(sourceRef.string("jobId") + "\n" + sourceRef.string("id"));
            }
            Set<String> seenSourceRefs = new HashSet<>();
            for (Obj row : rowsByRelation.getOrDefault(relationId, List.of())) {
                if (!issueId.equals(row.string("issueId")) || !companyId.equals(row.string("companyId"))) {
                    throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
                }
                Obj sourceRelation = row.object("sourceRelation").exactly(Set.of("jobId", "relationCandidateId"));
                String sourceKey = sourceRelation.string("jobId") + "\n" + sourceRelation.string("relationCandidateId");
                if (!sourceRefs.contains(sourceKey) || !seenSourceRefs.add(sourceKey)) {
                    throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
                }
                if (!"verified".equals(row.string("status"))) continue;

                String label = row.string("label");
                if (!Set.of("positive", "negative", "mixed", "undetermined").contains(label)) {
                    throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
                }
                Obj effects = row.object("effects").exactly(Set.of("positive", "negative", "neutral", "uncertain"));
                List<String> positive = effects.strings("positive");
                List<String> negative = effects.strings("negative");
                List<String> neutral = effects.strings("neutral");
                List<String> uncertain = effects.strings("uncertain");
                Set<String> cited = new TreeSet<>();
                cited.addAll(positive);
                cited.addAll(negative);
                cited.addAll(neutral);
                cited.addAll(uncertain);
                if (cited.isEmpty() || positive.size() + negative.size() + neutral.size() + uncertain.size() != cited.size()) {
                    throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
                }
                if (cited.stream().anyMatch(id -> !evidence.shownNow(id, round, evidenceGraphVersion,
                        requestedAsOf, requestId))) {
                    evidenceUnavailable = true;
                    continue;
                }
                String impactId = impactId(pinned.selected().version().id(), relationId, sourceKey);
                verified.add(new ImpactCandidate(relationId, sourceKey,
                        new CompanyIssueImpactResponse.Result(impactId, "verified", label, List.copyOf(cited),
                                new CompanyIssueImpactResponse.Effects(positive, negative, neutral, uncertain))));
            }
            if (!seenSourceRefs.containsAll(sourceRefs)) throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        }
        if (evidenceUnavailable) return new Impact("unavailable", "evidence_unavailable", List.of());
        if (verified.isEmpty()) {
            return new Impact("unavailable", "not_verified", List.of());
        }
        List<CompanyIssueImpactResponse.Result> results = verified.stream()
                .sorted(Comparator.comparing(ImpactCandidate::relationId).thenComparing(ImpactCandidate::sourceKey))
                .map(ImpactCandidate::result).toList();
        return new Impact("available", null, results);
    }

    private static final Set<String> IMPACT_ROW_KEYS = Set.of("edgeId", "issueId", "companyId", "sourceRelation",
            "impactCandidateId", "status", "code", "label", "targetVerdict", "effects", "verifier",
            "verifierRequestDigest", "proposal");

    private static String impactId(String versionId, String relationId, String sourceKey) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256")
                    .digest((versionId + "|" + relationId + "|" + sourceKey).getBytes(StandardCharsets.UTF_8));
            return "impact-" + HexFormat.of().formatHex(digest);
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException(impossible);
        }
    }

    private record ImpactCandidate(String relationId, String sourceKey, CompanyIssueImpactResponse.Result result) { }

    /** The receipt is support data only; pathCompanies are never emitted unless the selected graph has them as public nodes. */
    private BusinessPath businessPath(PublicGraphReader.Pinned pinned, DisplayGraph.Edge edge, String issueId,
            String round, String graphVersion, Instant requestedAsOf, String requestId) {
        try {
            return readBusinessPath(pinned, edge, issueId, round, graphVersion, requestedAsOf, requestId);
        } catch (StrictJson.Malformed malformed) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, malformed);
        }
    }

    private BusinessPath readBusinessPath(PublicGraphReader.Pinned pinned, DisplayGraph.Edge edge, String issueId,
            String round, String graphVersion, Instant requestedAsOf, String requestId) {
        if (!receiptBacked(pinned)) return new BusinessPath("unavailable", "not_recorded", List.of(), List.of());
        Obj bundle = evidence.graphImportBundle(pinned.selected().version().id(), requestId);
        String schema = bundle.string("schemaVersion");
        if (LEGACY_BUNDLE_SCHEMAS.contains(schema)) {
            return new BusinessPath("unavailable", "legacy_data", List.of(), List.of());
        }
        if (!SUPPORTED_BUNDLE_SCHEMAS.contains(schema)) throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        Map<String, Obj> receiptRelations = index(bundle.objects("relations"), "id");
        List<PathCandidate> candidates = new java.util.ArrayList<>();
        String unavailableReason = "not_recorded";
        boolean sawUnmapped = false;
        boolean sawPrivateOrUnlinked = false;
        boolean sawUnreadableEvidence = false;
        boolean sawIncomplete = false;
        DisplayGraph graph = pinned.graph();
        Map<String, Relation> snapshotRelations = snapshotRelationIndex(graph);
        Map<String, String> articleKeyByEvidence = new HashMap<>();
        Map<String, Boolean> evidenceVisibility = new HashMap<>();
        graph.snapshot.evidence().forEach(item -> articleKeyByEvidence.put(item.evidenceId(),
                item.articleId() + "@" + item.articleVersion()));

        for (String relationId : edge.relationIds()) {
            Obj relation = receiptRelations.get(relationId);
            if (relation == null) throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
            if (!"STRUCTURALLY_RELATED_TO".equals(relation.string("type"))
                    || !issueId.equals(relation.string("source")) || !edge.target().equals(relation.string("target"))) {
                throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
            }
            if (!relation.has("structuralPath") || relation.isNull("structuralPath")) {
                sawIncomplete = true;
                continue;
            }
            Relation visibleRelation = snapshotRelations.get(relationId);
            if (visibleRelation == null) throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
            List<Obj> bases = relation.objects("basis");
            Map<String, Obj> basesById = index(bases, "relationKey");
            if (bases.size() != visibleRelation.basis().size()
                    || visibleRelation.basis().stream().anyMatch(item -> !basesById.containsKey(item.basisId()))) {
                sawIncomplete = true;
                continue;
            }
            Obj path = relation.object("structuralPath");
            String status = path.string("status");
            if ("unavailable".equals(status)) {
                path.exactly(Set.of("status", "reason"));
                if (!"intermediate_company_unmapped".equals(path.string("reason"))) {
                    throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
                }
                if ("intermediate_company_unmapped".equals(path.string("reason"))) sawUnmapped = true;
                sawIncomplete = true;
                continue;
            }
            if (!"complete".equals(status)) throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
            path.exactly(Set.of("status", "companyIds", "links"));

            List<String> companyIds = path.strings("companyIds");
            List<Obj> rawLinks = path.objects("links");
            if (companyIds.size() < 2 || companyIds.size() > 3 || rawLinks.size() != companyIds.size() - 1
                    || bases.size() != rawLinks.size() || !companyIds.get(companyIds.size() - 1).equals(edge.target())
                    || new HashSet<>(companyIds).size() != companyIds.size()) {
                throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
            }
            if (companyIds.stream().anyMatch(id -> !graph.companies.containsKey(id))) {
                sawPrivateOrUnlinked = true;
                sawIncomplete = true;
                continue;
            }
            String firstCompanyId = companyIds.get(0);
            DisplayGraph.Edge start = graph.edges.values().stream()
                    .filter(candidate -> !candidate.derived() && "INVOLVES".equals(candidate.relationType())
                            && candidate.source().equals(issueId) && candidate.target().equals(firstCompanyId))
                    .findFirst().orElse(null);
            if (start == null) {
                sawPrivateOrUnlinked = true;
                sawIncomplete = true;
                continue;
            }
            if (start.evidenceIds().isEmpty()) {
                sawPrivateOrUnlinked = true;
                sawIncomplete = true;
                continue;
            }
            Set<String> allEvidence = new TreeSet<>(edge.evidenceIds());
            allEvidence.addAll(start.evidenceIds());
            List<BusinessLink> links = new java.util.ArrayList<>();
            for (int index = 0; index < rawLinks.size(); index++) {
                Obj rawLink = rawLinks.get(index);
                rawLink.exactly(Set.of("supplierCompanyId", "customerCompanyId"));
                Obj basis = bases.get(index);
                String supplier = rawLink.string("supplierCompanyId");
                String customer = rawLink.string("customerCompanyId");
                if (!adjacent(supplier, customer, companyIds.get(index), companyIds.get(index + 1))) {
                    throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
                }
                List<String> evidenceIds = basis.strings("evidenceIds");
                if (evidenceIds.isEmpty()) throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
                Basis visibleBasis = visibleRelation.basis().stream()
                        .filter(item -> item.basisId().equals(basis.string("relationKey"))).findFirst()
                        .orElseThrow(() -> new CustomException(ErrorCode.SOURCE_UNAVAILABLE));
                validateBasis(basis, visibleBasis, evidenceIds, articleKeyByEvidence);
                allEvidence.addAll(evidenceIds);
                String reason = businessReason(basis);
                links.add(new BusinessLink(supplier, customer, reason, evidenceIds));
            }
            String evidenceGraphVersion = round == null ? pinned.selected().version().id() : graphVersion;
            if (allEvidence.stream().anyMatch(id -> !evidenceVisibility.computeIfAbsent(id,
                    key -> evidence.shownNow(key, round, evidenceGraphVersion, requestedAsOf, requestId)))) {
                sawUnreadableEvidence = true;
                sawIncomplete = true;
                continue;
            }
            String firstEvidenceId = allEvidence.isEmpty() ? "" : allEvidence.iterator().next();
            candidates.add(new PathCandidate(companyIds, links, relationId, firstEvidenceId));
        }

        if (sawIncomplete) candidates.clear();
        if (!candidates.isEmpty()) {
            PathCandidate selected = candidates.stream().min(Comparator
                    .comparingInt((PathCandidate candidate) -> candidate.links().size())
                    .thenComparing(PathCandidate::relationId)
                    .thenComparing(PathCandidate::firstEvidenceId)).orElseThrow();
            return new BusinessPath("complete", null, selected.companyIds(), selected.links());
        }
        if (sawUnreadableEvidence) unavailableReason = "evidence_unavailable";
        else if (sawPrivateOrUnlinked) unavailableReason = "not_public";
        else if (sawUnmapped) unavailableReason = "intermediate_company_unmapped";
        else if (sawIncomplete) unavailableReason = "incomplete";
        return new BusinessPath("unavailable", unavailableReason, List.of(), List.of());
    }

    private static boolean adjacent(String supplier, String customer, String from, String to) {
        return (supplier.equals(from) && customer.equals(to)) || (supplier.equals(to) && customer.equals(from));
    }

    static String businessReason(Obj basis) {
        String relationType = basis.string("relationType");
        if (!"SUPPLIES".equals(relationType)) throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        String businessScope = basis.stringOrNull("businessScope");
        String productScope = basis.stringOrNull("productScope");
        List<String> scopes = java.util.stream.Stream.of(businessScope, productScope).filter(value -> value != null && !value.isBlank())
                .toList();
        return scopes.isEmpty() ? "공급" : "공급 · " + String.join(" · ", scopes);
    }

    private static final Set<String> SUPPORTED_BUNDLE_SCHEMAS = Set.of("zoop-graph-handoff-bundle-5",
            "zoop-graph-handoff-bundle-6", "zoop-graph-handoff-bundle-7");
    private static final Set<String> LEGACY_BUNDLE_SCHEMAS = Set.of("zoop-graph-handoff-bundle-1",
            "zoop-graph-handoff-bundle-2", "zoop-graph-handoff-bundle-3", "zoop-graph-handoff-bundle-4");

    private static boolean receiptBacked(PublicGraphReader.Pinned pinned) {
        return "snapshot".equals(pinned.selected().version().kind()) && !pinned.selected().reconstructed();
    }

    private static Map<String, Obj> index(List<Obj> rows, String key) {
        Map<String, Obj> result = new HashMap<>();
        for (Obj row : rows) {
            if (result.putIfAbsent(row.string(key), row) != null) throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        }
        return result;
    }

    private static Map<String, Relation> snapshotRelationIndex(DisplayGraph graph) {
        Map<String, Relation> result = new HashMap<>();
        for (Relation relation : graph.snapshot.relations()) {
            if (result.putIfAbsent(relation.relationId(), relation) != null) {
                throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
            }
        }
        return result;
    }

    private static void validateBasis(Obj basis, Basis visible, List<String> evidenceIds,
            Map<String, String> articleKeyByEvidence) {
        if (!"SUPPLIES".equals(basis.string("relationType"))
                || !visible.relationType().equals(basis.string("relationType"))
                || !parseOffsetInstant(visible.verifiedAt()).equals(parseOffsetInstant(basis.string("verifiedAt")))
                || !java.util.Objects.equals(visible.validFrom(), basis.stringOrNull("validFrom"))
                || !java.util.Objects.equals(visible.validUntil(), basis.stringOrNull("validUntil"))
                || !visible.countries().equals(basis.strings("countries"))) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        }
        Set<String> receiptArticles = new HashSet<>();
        for (Obj article : basis.objects("sourceArticles")) {
            receiptArticles.add(article.string("articleId") + "@" + article.string("articleVersion"));
        }
        Set<String> snapshotArticles = visible.articles().stream()
                .map(article -> article.articleId() + "@" + article.articleVersion())
                .collect(java.util.stream.Collectors.toSet());
        Set<String> citedArticles = new HashSet<>();
        for (String evidenceId : evidenceIds) {
            String articleKey = articleKeyByEvidence.get(evidenceId);
            if (articleKey == null) throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
            citedArticles.add(articleKey);
        }
        if (!receiptArticles.equals(snapshotArticles) || !citedArticles.equals(receiptArticles)) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        }
    }

    private static String parseOffsetInstant(String value) {
        try { return java.time.OffsetDateTime.parse(value).toInstant().toString(); }
        catch (DateTimeParseException exception) { throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, exception); }
    }

    private record PathCandidate(List<String> companyIds, List<BusinessLink> links, String relationId,
            String firstEvidenceId) {
        private PathCandidate {
            companyIds = List.copyOf(companyIds);
            links = List.copyOf(links);
        }
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
