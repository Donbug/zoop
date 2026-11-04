package com.zoop.briefing.personal;

import com.zoop.briefing.query.BriefingGraphContentAuthority;
import com.zoop.document.analysis.GrantRegistry;
import com.zoop.briefing.storage.BriefingRound;
import com.zoop.document.evidence.config.DocumentReadProperties;
import com.zoop.document.evidence.service.DocumentReadGrants;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import tools.jackson.databind.JsonNode;
import java.time.Clock;
import java.util.List;

/** Recheck CURRENT document rights and graph-source authority for each candidate, never the saved boolean. */
@Component
public class PersonalCandidateAccess {
    private final JdbcTemplate jdbc;
    private final DocumentReadGrants grants;
    private final Clock clock;
    private final BriefingGraphContentAuthority authority;
    private final com.zoop.briefing.query.SavedBriefingBasisAuthority retained;
    public PersonalCandidateAccess(JdbcTemplate jdbc, DocumentReadProperties properties, Clock clock, BriefingGraphContentAuthority authority) {
        this.jdbc=jdbc; this.grants=new DocumentReadGrants(properties.grantsPath()); this.clock=clock; this.authority=authority;
        this.retained=new com.zoop.briefing.query.SavedBriefingBasisAuthority(jdbc,properties.artifactRootPath());
    }
    public boolean readableForRound(JsonNode candidate, BriefingRound round, String requestId) {
        var graph=authority.context(round.graphVersion(),requestId);
        if(round.publicSnapshot()!=null&&round.publicSnapshot().has("retainedBasis")
                &&!retained.allowsCandidate(round.payload(),round.publicSnapshot(),candidate))return false;
        return readable(candidate,graph,requestId);
    }
    public boolean readable(JsonNode candidate, BriefingGraphContentAuthority.Context graph, String requestId) {
        if (!graph.allowsCandidate(candidate)) return false;
        var current=grants.registry(requestId);
        if (!candidate.path("sources").isArray() || candidate.path("sources").isEmpty()) return false;
        for (var source : candidate.path("sources")) {
            var bindings=jdbc.queryForList("""
                SELECT a.provider,t.sha256,v.published_at,v.published_date,v.publication_precision,v.collected_at FROM articles a JOIN article_versions v ON v.article_id=a.id
                JOIN artifacts t ON t.id=v.text_artifact_id
                WHERE a.id=? AND v.version=? AND a.access_status='available'
                """,
                source.path("documentId").asString(),source.path("documentVersion").asString());
            if (bindings.size()!=1 || !bindings.getFirst().get("sha256").equals(source.path("bodySha256").asString())) return false;
            try { if(!com.zoop.briefing.server.BriefingSourceClock.read(bindings.getFirst()).matches(com.zoop.common.json.StrictJson.Obj.of(source)))return false; }
            catch(IllegalArgumentException invalidClock){return false;}
            var recipients=source.path("recipients").valueStream().map(JsonNode::asString).toList();
            if (recipients.isEmpty() || GrantRegistry.evaluateBriefingRead(current.current(source.path("grantId").asString()).orElse(null),
                    bindings.getFirst().get("provider").toString(),source.path("grantRevision").asString(),
                    recipients,clock.instant())!=null) return false;
        }
        return true;
    }
}
