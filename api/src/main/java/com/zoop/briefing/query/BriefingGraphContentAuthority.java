package com.zoop.briefing.query;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.graph.publication.GraphPublicationAuthority;
import com.zoop.graph.publication.GraphPublicationReader;
import com.zoop.graph.publication.PublicationException;
import com.zoop.graph.read.GraphSnapshotFilter;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import com.zoop.graph.version.GraphVersionRepository;
import java.util.HashSet;
import java.util.Set;
import org.springframework.stereotype.Component;
import tools.jackson.databind.JsonNode;

/** Current original-source proof for retained briefing text; never calls the public graph/briefing selector. */
@Component
public class BriefingGraphContentAuthority {
    private final GraphVersionRepository versions;
    private final GraphPublicationReader publications;
    private final GraphPublicationAuthority authority;

    public BriefingGraphContentAuthority(GraphVersionRepository versions, GraphPublicationReader publications,
            GraphPublicationAuthority authority) {
        this.versions = versions;
        this.publications = publications;
        this.authority = authority;
    }

    public Context context(String graphVersion, String requestId) {
        if (graphVersion == null) return Context.UNBOUND;
        try {
            var version = versions.find(graphVersion);
            // Historical fixture rounds can have a synthetic version label without a registered imported graph.
            if (version.isEmpty()) {
                if (graphVersion.startsWith("gv-")) unavailable();
                return Context.UNBOUND;
            }
            if ("fixture".equals(version.get().kind())) return Context.UNBOUND;
            if (!"snapshot".equals(version.get().kind())) unavailable();
            var publication = publications.read(graphVersion);
            var exclusions = authority.current(publication, requestId);
            var visible = GraphSnapshotFilter.apply(publication.snapshot(), null, exclusions);
            return new Context(publication.snapshot(), visible);
        } catch (PublicationException error) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, false);
        }
    }

    public record Context(PublicGraphSnapshot snapshot, PublicGraphSnapshot visible) {
        private static final Context UNBOUND = new Context(null, null);

        public boolean allowsRound(JsonNode payload, Set<String> disclosedEvidence) {
            if (snapshot == null) return true;
            if (!payload.path("references").path("eventIds").isArray()) return false;
            for (JsonNode ref : payload.path("references").path("eventIds")) {
                if (visible.issues().stream().noneMatch(i -> i.issueId().equals(ref.asString("")))) return false;
            }
            Set<String> issues = new HashSet<>();
            for (JsonNode item : payload.path("items")) {
                String id = item.path("eventId").asString("");
                if (id.isBlank() || !issues.add(id) || snapshot.issues().stream().noneMatch(i -> id.equals(i.issueId()))
                        || visible.issues().stream().noneMatch(i -> id.equals(i.issueId()))) return false;
                for (JsonNode evidence : item.path("evidenceIds")) {
                    if (!allowsEvidence(evidence.asString(""), id)) return false;
                }
                if (!item.path("companies").isArray()) return false;
                for (JsonNode company : item.path("companies")) {
                    String companyId = company.path("id").asString("");
                    String type = company.path("relationType").asString("");
                    if (!Set.of("INVOLVES", "STRUCTURALLY_RELATED_TO").contains(type)
                            || !allowsRelations(Set.of(id), companyId, type)) return false;
                }
            }
            for (String evidence : disclosedEvidence) if (!allowsEvidence(evidence, null)) return false;
            return true;
        }

        public boolean allowsCandidate(JsonNode candidate) {
            if (snapshot == null) return true;
            if (!candidate.path("sources").isArray() || candidate.path("sources").isEmpty()) return false;
            Set<String> sourceEvidence = new HashSet<>();
            for (JsonNode source : candidate.path("sources")) {
                String evidenceId = source.path("evidenceId").asString("");
                String articleId = source.path("documentId").asString("");
                String version = source.path("documentVersion").asString("");
                if (!sourceEvidence.add(evidenceId) || snapshot.issues().stream().noneMatch(i -> i.evidenceIds().contains(evidenceId)
                        || i.geographyEvidenceIds().contains(evidenceId))) return false;
                if (!allowsEvidence(evidenceId, null) || snapshot.evidence().stream().noneMatch(e -> evidenceId.equals(e.evidenceId())
                        && articleId.equals(e.articleId()) && version.equals(e.articleVersion()))) return false;
            }
            if (!candidate.path("companies").isArray()) return false;
            Set<String> sourceIssues = new HashSet<>();
            for (var issue : snapshot.issues()) {
                if (issue.evidenceIds().stream().anyMatch(sourceEvidence::contains)
                        || issue.geographyEvidenceIds().stream().anyMatch(sourceEvidence::contains)) sourceIssues.add(issue.issueId());
            }
            for (JsonNode company : candidate.path("companies")) {
                String companyId = company.path("companyId").asString("");
                if (!company.path("evidenceIds").isArray() || company.path("evidenceIds").isEmpty()) return false;
                for (JsonNode id : company.path("evidenceIds")) {
                    if (!sourceEvidence.contains(id.asString(""))) return false;
                }
                if (!allowsRelations(sourceIssues, companyId, null)) return false;
            }
            return true;
        }

        private boolean allowsEvidence(String id, String issueId) {
            if (id.isBlank()) return false;
            var source = snapshot.evidence().stream().filter(e -> id.equals(e.evidenceId())).toList();
            if (source.size() != 1 || visible.evidence().stream().noneMatch(e -> e.equals(source.getFirst()))) return false;
            if (snapshot.issues().stream().filter(i -> i.evidenceIds().contains(id) || i.geographyEvidenceIds().contains(id))
                    .anyMatch(i -> visible.issues().stream().noneMatch(v -> v.issueId().equals(i.issueId())))) return false;
            return issueId == null || snapshot.issues().stream().anyMatch(i -> issueId.equals(i.issueId())
                    && (i.evidenceIds().contains(id) || i.geographyEvidenceIds().contains(id)));
        }

        private boolean allowsRelations(Set<String> issueIds, String companyId, String type) {
            if (issueIds.isEmpty() || companyId.isBlank()) return false;
            for (String issue : issueIds) {
                var relations = snapshot.relations().stream().filter(r -> issue.equals(r.source())
                        && companyId.equals(r.target()) && Set.of("INVOLVES", "STRUCTURALLY_RELATED_TO").contains(r.relationType())
                        && (type == null || type.equals(r.relationType()))).toList();
                if (relations.isEmpty() || relations.stream().anyMatch(r -> !visible.relations().contains(r))) return false;
            }
            return true;
        }
    }

    private static void unavailable() { throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, false); }
}
