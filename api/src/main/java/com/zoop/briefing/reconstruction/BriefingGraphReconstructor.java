package com.zoop.briefing.reconstruction;

import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.briefing.query.BriefingQueryService;
import com.zoop.briefing.replay.BriefingReplayGuard;
import com.zoop.briefing.replay.BriefingReplayReadPolicy;
import com.zoop.briefing.storage.BriefingRound;
import com.zoop.briefing.storage.BriefingRoundRepository;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import com.zoop.document.repository.ArtifactRow;
import com.zoop.document.repository.DocumentRegistryRepository;
import com.zoop.graph.snapshot.GraphSnapshotCodec;
import java.nio.file.Path;
import java.time.Clock;
import java.time.Instant;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ObjectNode;

/** Explicit local replay operation; no external fetch/model call, original update, publication or activation. */
@Service
public class BriefingGraphReconstructor {
    private final BriefingRoundRepository rounds;
    private final BriefingQueryService publications;
    private final DocumentRegistryRepository registry;
    private final BriefingReplayReadPolicy replay;
    private final JdbcTemplate jdbc;
    private final Clock clock;
    private final TransactionTemplate transaction;

    public BriefingGraphReconstructor(BriefingRoundRepository rounds, BriefingQueryService publications,
            DocumentRegistryRepository registry, BriefingReplayReadPolicy replay, JdbcTemplate jdbc,
            PlatformTransactionManager transactions, Clock clock) {
        this.rounds = rounds; this.publications = publications; this.registry = registry; this.replay = replay;
        this.jdbc = jdbc; this.clock = clock; this.transaction = new TransactionTemplate(transactions);
        this.transaction.setIsolationLevel(org.springframework.transaction.TransactionDefinition.ISOLATION_REPEATABLE_READ);
    }

    public String reconstruct(String roundId, Path artifactRoot) {
        BriefingReplayGuard.database(jdbc);
        try (var session = ArtifactFileStore.at(artifactRoot).open()) {
            return transaction.execute(status -> {
                var row = rounds.findById(roundId).orElseThrow(() -> new IllegalArgumentException("Unknown round"));
                require(row.graphVersion() == null && BriefingReplayReadPolicy.marked(row) && replay.permits(row), "not_local_legacy_replay");
                publications.get(row.date(), row.edition(), "graph-reconstruction"); // original/current source authority
                var sources = new LinkedHashMap<String, BriefingRoundRepository.ItemEvidence>();
                for (var item : row.payload().path("items")) {
                    publications.getItem(row.id(), item.path("eventId").asString(), "graph-reconstruction");
                    for (var id : item.path("evidenceIds")) {
                        var source = rounds.findItemEvidence(id.asString()).orElseThrow(() -> new IllegalArgumentException("Evidence unavailable"));
                        sources.put(source.id(), source);
                    }
                }
                String id = BriefingGraphReconstruction.id(row);
                byte[] bytes = Canonical.appBytes(build(row, id, sources));
                GraphSnapshotCodec.readReconstruction(bytes, id);
                var file = session.put("briefing_graphs", id + ".json", bytes);
                var artifact = new ArtifactRow(id, "graph_snapshot", file.uri(), file.sha256(), file.bytes(), "application/json", clock.instant());
                registry.insertArtifactIfAbsent(artifact);
                var saved = registry.findArtifact(id).orElseThrow();
                require(saved.kind().equals(artifact.kind()) && saved.storageUri().equals(artifact.storageUri())
                        && saved.sha256().equals(artifact.sha256()) && saved.bytes() == artifact.bytes()
                        && saved.mediaType().equals(artifact.mediaType()), "artifact_conflict");
                return id;
            });
        }
    }

    /** Projection only: chronology and roles stay as stored; unknown geography/action/target are not guessed. */
    static ObjectNode build(BriefingRound row, String id, Map<String, BriefingRoundRepository.ItemEvidence> sources) {
        var root = StrictJson.newObject().put("snapshotFormat", 3).put("versionId", id)
                .put("sourceBundleId", BriefingGraphReconstruction.POLICY + ":" + id);
        var companies = root.putArray("companies"); var issues = root.putArray("issues");
        var relations = root.putArray("relations"); var articles = root.putArray("articles"); var evidence = root.putArray("evidence");
        Set<String> companyIds = new HashSet<>(), articleKeys = new HashSet<>(), evidenceIds = new HashSet<>();
        for (var item : row.payload().path("items")) {
            String event = item.path("eventId").asString();
            var issue = issues.addObject().put("issueId", event).put("label", item.path("title").asString())
                    .put("timePrecision", item.path("timePrecision").asString()).putNull("period").putNull("assertionStatus")
                    .putNull("action").putNull("target").putNull("geography").put("geographyPolicyVersion", "not_recorded");
            issue.set("eventTime", item.path("eventTime").deepCopy()); issue.putArray("geographyEvidenceIds");
            var issueArticles = issue.putArray("articleIds"); var issueEvidence = issue.putArray("evidenceIds");
            var mentions = issue.putArray("mentions"); Set<String> mentionArticles = new HashSet<>(); Instant latest = null;
            for (JsonNode ref : item.path("evidenceIds")) {
                var source = sources.get(ref.asString()); require(source != null, "missing_evidence");
                require(source.publishedAt() != null && !source.publishedAt().isAfter(row.windowTo()), "evidence_after_cutoff");
                require(source.start() >= 0 && source.end() > source.start() && source.end() <= Integer.MAX_VALUE, "evidence_span");
                if (latest == null || source.publishedAt().isAfter(latest)) latest = source.publishedAt();
                issueEvidence.add(source.id());
                String key = source.documentId() + "@" + source.documentVersion();
                if (mentionArticles.add(key)) {
                    issueArticles.add(source.documentId());
                    mentions.addObject().put("mentionId", "brf-mention-" + Canonical.sha256(event + "\n" + key))
                            .put("articleId", source.documentId()).put("articleVersion", source.documentVersion());
                }
                if (articleKeys.add(key)) articles.addObject().put("articleId", source.documentId()).put("version", source.documentVersion())
                        .put("title", source.title()).put("url", source.url()).put("publishedAt", source.publishedAt().toString());
                if (evidenceIds.add(source.id())) evidence.addObject().put("evidenceId", source.id()).put("articleId", source.documentId())
                        .put("articleVersion", source.documentVersion()).put("start", (int) source.start()).put("end", (int) source.end());
            }
            require(latest != null, "issue_without_evidence"); issue.put("latestPublishedAt", latest.toString());
            for (var company : item.path("companies")) {
                require("INVOLVES".equals(company.path("relationType").asString()), "unrecorded_structural_basis");
                String companyId = company.path("id").asString();
                if (companyIds.add(companyId)) companies.addObject().put("companyId", companyId).put("label", company.path("name").asString());
                var relation = relations.addObject().put("relationId", "brf-relation-" + Canonical.sha256(event + "\n" + companyId))
                        .put("source", event).put("target", companyId).put("relationType", "INVOLVES").putNull("assertionStatus");
                relation.set("role", company.path("roleUnconfirmed").asBoolean() ? StrictJson.newObject().nullNode() : company.path("role").deepCopy());
                relation.set("evidenceIds", item.path("evidenceIds").deepCopy()); relation.putArray("basis");
            }
        }
        return root;
    }

    private static void require(boolean condition, String reason) {
        if (!condition) throw new IllegalArgumentException("Briefing graph reconstruction: " + reason);
    }
}
