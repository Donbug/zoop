package com.zoop.briefing.query;

import java.time.Clock;
import java.time.Instant;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.LinkedHashSet;
import java.util.Map;
import java.util.Set;

import com.zoop.briefing.storage.BriefingRound;
import com.zoop.briefing.replay.BriefingReplayReadPolicy;
import com.zoop.common.json.StrictJson;
import com.zoop.document.analysis.GrantRegistry;
import com.zoop.document.evidence.config.DocumentReadProperties;
import com.zoop.document.evidence.service.DocumentReadGrants;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import org.springframework.beans.factory.annotation.Autowired;
import tools.jackson.databind.JsonNode;

/**
 * Read authority for an immutable briefing, using the existing document registry and the CURRENT operator grant file.
 * Missing/changed/expired/revoked authority fails closed. Database/registry failures propagate as unavailable, never an
 * empty successful briefing. No fixture switch, cached grant or publication-time boolean can authorize a response.
 */
@Component
public class DocumentBriefingContentAccess implements BriefingContentAccess {
    private static final Set<String> BINDING_FIELDS = Set.of("documentId", "documentVersion", "grantId", "grantRevision",
            "recipients");
    private static final List<String> PURPOSES = List.of("briefing-outlook", "semantic-verification");
    private final JdbcTemplate jdbc;
    private final DocumentReadGrants grants;
    private final Clock clock;
    private final BriefingReplayReadPolicy replay;

    public DocumentBriefingContentAccess(JdbcTemplate jdbc, DocumentReadProperties properties, Clock clock) {
        this(jdbc, properties, clock, BriefingReplayReadPolicy.disabled());
    }

    @Autowired
    public DocumentBriefingContentAccess(JdbcTemplate jdbc, DocumentReadProperties properties, Clock clock,
            BriefingReplayReadPolicy replay) {
        this.jdbc = jdbc;
        this.grants = new DocumentReadGrants(properties.grantsPath());
        this.clock = clock;
        this.replay = replay;
    }

    @Override
    public boolean mayRead(BriefingRound round, String requestId) {
        if (round.publishedAt() == null || round.payload() == null || round.publicSnapshot() == null) return false;
        if (BriefingReplayReadPolicy.marked(round) && !replay.permits(round)) return false;
        GrantRegistry current = grants.registry(requestId);
        Instant now = clock.instant();
        try {
            if (!sources(round.payload(), round.publicSnapshot(), current, now)) return false;
            JsonNode comparison = round.comparisonSnapshot();
            if (comparison != null && "available".equals(StrictJson.Obj.of(comparison).string("status"))) {
                // Comparison can disclose morning-only issues. Authorize that stored morning original as well.
                String morningId = nonBlank(StrictJson.Obj.of(comparison).string("morningRoundId"));
                List<Prior> prior = jdbc.query("""
                        SELECT m.id, m.published_payload, m.public_snapshot FROM briefing_rounds r
                        JOIN briefing_rounds m ON m.id=r.morning_round_id
                        WHERE r.id=? AND m.id=? AND m.edition='morning' AND m.round_date=r.round_date
                            AND m.published_at IS NOT NULL AND m.status='published'
                            AND m.payload_sha256=encode(sha256(convert_to(m.published_payload::text,'UTF8')),'hex')
                        """, (rs, index) -> new Prior(StrictJson.parseObject(rs.getString("published_payload")).node(),
                                StrictJson.parseObject(rs.getString("public_snapshot")).node()), round.id(), morningId);
                if (prior.size() != 1 || !sources(prior.get(0).payload(), prior.get(0).snapshot(), current, now)) return false;
            }
            return true;
        } catch (StrictJson.Malformed malformed) {
            return false;
        }
    }

    private boolean sources(JsonNode publishedPayload, JsonNode publicSnapshot, GrantRegistry current, Instant now) {
        try {
            List<StrictJson.Obj> bindings = StrictJson.Obj.of(publicSnapshot).objects("sourceBindings");
            // Even an honestly empty selected issue set must retain the real sources used to decide it was empty.
            if (bindings.isEmpty()) return false;
            Map<DocumentVersion, Binding> authorized = new HashMap<>();
            for (StrictJson.Obj object : bindings) {
                object.exactly(BINDING_FIELDS);
                Binding binding = new Binding(nonBlank(object.string("documentId")),
                        nonBlank(object.string("documentVersion")), nonBlank(object.string("grantId")),
                        nonBlank(object.string("grantRevision")), object.strings("recipients"));
                if (binding.recipients().isEmpty() || binding.recipients().stream().anyMatch(String::isBlank)
                        || new HashSet<>(binding.recipients()).size() != binding.recipients().size()) return false;
                DocumentVersion key = new DocumentVersion(binding.documentId(), binding.documentVersion());
                if (authorized.putIfAbsent(key, binding) != null) return false;
                List<String> providers = jdbc.query("""
                        SELECT a.provider FROM articles a JOIN article_versions v ON v.article_id=a.id
                        WHERE a.id=? AND v.version=? AND a.access_status='available'
                        """, (rs, index) -> rs.getString("provider"), binding.documentId(), binding.documentVersion());
                if (providers.size() != 1 || GrantRegistry.evaluate(current.current(binding.grantId()).orElse(null),
                        providers.get(0), binding.grantRevision(), PURPOSES, binding.recipients(), true, now) != null) {
                    return false;
                }
            }

            StrictJson.Obj payload = StrictJson.Obj.of(publishedPayload);
            List<String> referenceIds = payload.object("references").strings("evidenceIds");
            Set<String> references = new LinkedHashSet<>();
            for (String id : referenceIds) {
                if (id.isBlank() || !references.add(id)) return false;
            }
            Set<String> disclosedEvidence = new LinkedHashSet<>(references);
            summaryEvidence(StrictJson.Obj.of(publicSnapshot).raw("marketSummary"), disclosedEvidence);
            for (StrictJson.Obj item : payload.objects("items")) {
                List<String> evidenceIds = item.strings("evidenceIds");
                if (evidenceIds.isEmpty() || !references.containsAll(evidenceIds)) return false;
                summaryEvidence(item.raw("summary"), disclosedEvidence);
                JsonNode sentiments = item.raw("documentSentiments");
                if (!sentiments.isArray()) return false;
                for (JsonNode sentiment : sentiments.values()) {
                    String documentId = nonBlank(StrictJson.Obj.of(sentiment).string("articleId"));
                    if (authorized.keySet().stream().noneMatch(version -> version.documentId().equals(documentId))) {
                        return false;
                    }
                }
            }
            for (String id : disclosedEvidence) {
                List<DocumentVersion> source = jdbc.query("""
                        SELECT e.article_id, e.article_version FROM evidence e
                        JOIN article_versions v ON v.article_id=e.article_id AND v.version=e.article_version
                        JOIN articles a ON a.id=e.article_id
                        WHERE e.id=? AND a.access_status='available' AND e.quote_verified IS TRUE
                            AND e.verification_artifact_id IS NOT NULL AND e.text_artifact_id=v.text_artifact_id
                        """, (rs, index) -> new DocumentVersion(rs.getString("article_id"), rs.getString("article_version")), id);
                if (source.size() != 1 || !authorized.containsKey(source.get(0))) return false;
            }
            return true;
        } catch (StrictJson.Malformed malformed) {
            return false;
        }
    }

    private static void summaryEvidence(JsonNode node, Set<String> evidence) {
        StrictJson.Obj summary = StrictJson.Obj.of(node);
        if (summary.has("status")) {
            if (!"unavailable".equals(summary.string("status"))) throw new StrictJson.Malformed();
            return;
        }
        List<String> ids = summary.strings("evidenceIds");
        if (ids.isEmpty()) throw new StrictJson.Malformed();
        for (String id : ids) evidence.add(nonBlank(id));
    }

    private static String nonBlank(String value) {
        if (value.isBlank()) throw new StrictJson.Malformed();
        return value;
    }

    private record DocumentVersion(String documentId, String documentVersion) {
    }

    private record Binding(String documentId, String documentVersion, String grantId, String grantRevision,
            List<String> recipients) {
    }

    private record Prior(JsonNode payload, JsonNode snapshot) {
    }
}
