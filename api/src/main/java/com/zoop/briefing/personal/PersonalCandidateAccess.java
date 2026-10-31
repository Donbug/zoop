package com.zoop.briefing.personal;

import com.zoop.document.analysis.GrantRegistry;
import com.zoop.document.evidence.config.DocumentReadProperties;
import com.zoop.document.evidence.service.DocumentReadGrants;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import tools.jackson.databind.JsonNode;
import java.time.Clock;
import java.util.List;

/** Recheck CURRENT rights, article availability and exact body version; never authorize from the saved boolean. */
@Component
public class PersonalCandidateAccess {
    private final JdbcTemplate jdbc;
    private final DocumentReadGrants grants;
    private final Clock clock;
    public PersonalCandidateAccess(JdbcTemplate jdbc, DocumentReadProperties properties, Clock clock) {
        this.jdbc=jdbc; this.grants=new DocumentReadGrants(properties.grantsPath()); this.clock=clock;
    }
    public boolean readable(JsonNode candidate, String requestId) {
        var current=grants.registry(requestId);
        if (!candidate.path("sources").isArray() || candidate.path("sources").isEmpty()) return false;
        for (var source : candidate.path("sources")) {
            var bindings=jdbc.query("""
                SELECT a.provider,t.sha256,v.published_at FROM articles a JOIN article_versions v ON v.article_id=a.id
                JOIN artifacts t ON t.id=v.text_artifact_id
                WHERE a.id=? AND v.version=? AND a.access_status='available'
                """, (r,i)->List.of(r.getString(1),r.getString(2),r.getTimestamp(3).toInstant().toString()),
                source.path("documentId").asString(),source.path("documentVersion").asString());
            if (bindings.size()!=1 || !bindings.getFirst().get(1).equals(source.path("bodySha256").asString())) return false;
            if (!java.time.Instant.parse(bindings.getFirst().get(2)).equals(java.time.Instant.parse(source.path("publishedAt").asString()))) return false;
            var recipients=source.path("recipients").valueStream().map(JsonNode::asString).toList();
            if (recipients.isEmpty() || GrantRegistry.evaluate(current.current(source.path("grantId").asString()).orElse(null),
                    bindings.getFirst().getFirst(),source.path("grantRevision").asString(),
                    List.of("briefing-outlook","semantic-verification"),recipients,true,clock.instant())!=null) return false;
        }
        return true;
    }
}
