package com.zoop.briefing.replay;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermissions;
import java.sql.Timestamp;
import java.time.Instant;
import java.time.LocalDate;
import java.time.LocalTime;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

/**
 * Imports an already generated and independently verified historical development replay into a disposable local DB.
 * It makes no model/provider call and grants no operational source rights. The original source rows, including unknown
 * rights and late/estimated dates, are preserved in raw artifacts. A manifest published after commit is needed to read.
 */
public final class BriefingReplayImporter {
    private static final ZoneId KST = ZoneId.of("Asia/Seoul");
    private static final int MAX_FILE_BYTES = 128 * 1024 * 1024;
    private static final List<String> EDITIONS = List.of("morning", "evening");
    private static final Set<String> NOVELTY_STAGES = Set.of("round_simulation_novelty", "round_simulation_novelty_verification");
    private final JdbcTemplate jdbc;
    private final TransactionTemplate transaction;
    private final BriefingReplaySettings settings;

    public BriefingReplayImporter(JdbcTemplate jdbc, PlatformTransactionManager transactions, BriefingReplaySettings settings) {
        this.jdbc = jdbc; this.transaction = new TransactionTemplate(transactions); this.settings = settings;
        transaction.setTimeout(30);
    }

    public record ImportResult(String runId, List<String> roundIds, int documents, int evidence, int artifacts,
            boolean alreadyImported) { }

    public ImportResult importBundle() {
        BriefingReplayGuard.database(jdbc);
        byte[] sourceBytes = read(settings.source());
        String sourceSha = Canonical.sha256(sourceBytes);
        require(sourceSha.equals(settings.expectedSourceSha256()), "source_digest");
        byte[] bundleBytes = read(settings.bundle());
        String bundleSha = Canonical.sha256(bundleBytes);
        StrictJson.Obj bundle = StrictJson.parseObject(bundleBytes);
        rejectCredentialFields(bundle.node());
        if ("zoop-briefing-round-simulation-v2".equals(bundle.string("schemaVersion"))
                || BriefingGroupedSimulationRules.SCHEMA.equals(bundle.string("schemaVersion"))) {
            return importSimulation(sourceBytes, bundleBytes, bundle);
        }
        require("zoop-briefing-replay-v1".equals(bundle.string("schemaVersion")), "bundle_schema");
        require(sourceSha.equals(bundle.string("sourceFileSha256")), "bundle_source_digest");
        String run = text(bundle, "runId");
        require(run.matches("[A-Za-z0-9_-]{1,96}"), "run_id");
        if (Files.exists(settings.manifest(), LinkOption.NOFOLLOW_LINKS)) {
            StrictJson.Obj prior = StrictJson.parseObject(read(settings.manifest()));
            require("development_replay".equals(prior.string("scope")) && run.equals(prior.string("runId"))
                    && sourceSha.equals(prior.string("sourceFileSha256")) && bundleSha.equals(prior.string("bundleSha256"))
                    && settings.userInboxRef().equals(prior.string("userInboxRef")), "manifest_identity_conflict");
        }
        StrictJson.Obj authorization = bundle.object("authorization");
        require("development_replay".equals(authorization.string("scope"))
                && sourceSha.equals(authorization.string("sourceSha256"))
                && settings.userInboxRef().equals(authorization.string("userInboxRef")), "authorization_scope");
        StrictJson.Obj history = bundle.object("historicalReplay");
        LocalDate from = LocalDate.parse(history.object("sourcePeriod").string("start"));
        LocalDate to = LocalDate.parse(history.object("sourcePeriod").string("end"));
        LocalDate date = LocalDate.parse(history.string("roundDate"));
        require(!to.isBefore(from) && date.isAfter(to) && history.bool("sameSourcePoolForBothEditions"), "historical_window");
        Map<String, Source> sourcePool = sources(sourceBytes);
        Map<String, Issue> selected = selections(bundle, sourcePool);
        Map<String, StrictJson.Obj> generated = new LinkedHashMap<>();
        for (String edition : EDITIONS) {
            StrictJson.Obj result = bundle.object("editions").object(edition);
            validateGeneration(result, selected);
            generated.put(edition, result);
        }
        validateReceipts(bundle, generated);

        String namespace = "brf-replay-" + Canonical.sha256(run).substring(0, 16);
        Map<String, Source> documents = new LinkedHashMap<>();
        Map<String, Citation> citations = new LinkedHashMap<>();
        for (Issue issue : selected.values()) for (Citation citation : issue.citations()) {
            documents.putIfAbsent(citation.source().key(), citation.source());
            Citation prior = citations.putIfAbsent(citation.id(), citation);
            require(prior == null || prior.equals(citation), "evidence_identity_conflict");
        }
        Map<String, Blob> blobs = new LinkedHashMap<>();
        blobs.put(namespace + "-bundle", blob("ai_submit", bundleBytes));
        ObjectNode input = StrictJson.newObject().put("sourceFileSha256", sourceSha).put("runId", run);
        input.set("authorization", authorization.node().deepCopy());
        input.set("historicalReplay", history.node().deepCopy()); input.set("selected", bundle.array("selected").deepCopy());
        blobs.put(namespace + "-input", blob("briefing_input", StrictJson.write(input)));
        sourceBlobs(namespace, sourceSha, documents, citations, blobs);
        for (var entry : generated.entrySet()) {
            blobs.put(namespace + "-" + entry.getKey() + "-result", blob("analysis_result", StrictJson.write(entry.getValue().node())));
            blobs.put(namespace + "-" + entry.getKey() + "-verification", blob("verification_receipt",
                    StrictJson.write(entry.getValue().object("verification").node())));
        }
        int receiptIndex = 0;
        for (StrictJson.Obj receipt : bundle.objects("receipts")) {
            blobs.put(namespace + "-usage-" + receiptIndex++, blob("ai_call_receipt", StrictJson.write(receipt.node())));
        }
        ObjectNode grants = grants(run, sourceSha, documents.values().stream().toList());
        byte[] grantsBytes = StrictJson.write(grants);
        checkExisting(settings.grants(), grantsBytes);
        Instant created = generated.values().stream().map(value -> Instant.parse(value.string("generatedAt"))).max(Instant::compareTo).orElseThrow();
        List<Round> rounds = new ArrayList<>();
        for (String edition : EDITIONS) {
            rounds.add(round(namespace, edition, date, from, sourceSha, bundleSha, run, history, selected,
                    generated.get(edition), documents, created));
        }

        ArtifactFileStore store = ArtifactFileStore.at(settings.artifactRoot());
        try (ArtifactFileStore.Session files = store.open()) {
            Map<String, ArtifactFileStore.StoredFile> stored = new LinkedHashMap<>();
            blobs.forEach((id, content) -> stored.put(id, files.put("briefing_replay", id + ".bin", content.bytes())));
            Boolean existed = transaction.execute(status -> {
                jdbc.execute("SELECT pg_advisory_xact_lock(hashtext('briefing_development_replay'))");
                int existingRounds = 0;
                for (Round round : rounds) {
                    List<String> existing = jdbc.query("SELECT id FROM briefing_rounds WHERE id=?", (rs, n) -> rs.getString(1), round.id());
                    existingRounds += existing.size();
                }
                require(existingRounds == 0 || existingRounds == rounds.size(), "partial_replay_conflict");
                for (var entry : blobs.entrySet()) register(entry.getKey(), entry.getValue(), stored.get(entry.getKey()), created);
                for (Source source : documents.values()) registerDocument(namespace, source);
                for (Citation citation : citations.values()) registerEvidence(namespace, citation, created);
                for (Round round : rounds) registerRound(round);
                return existingRounds == rounds.size();
            });
            ObjectNode manifest = StrictJson.newObject().put("schemaVersion", "zoop-briefing-replay-manifest-v1")
                    .put("scope", "development_replay").put("runId", run).put("sourceFileSha256", sourceSha)
                    .put("bundleSha256", bundleSha).put("userInboxRef", settings.userInboxRef())
                    .put("grantsSha256", Canonical.sha256(grantsBytes));
            manifest.set("historicalReplay", history.node().deepCopy());
            ArrayNode manifestRounds = manifest.putArray("rounds");
            for (Round round : rounds) manifestRounds.addObject().put("id", round.id())
                    .put("payloadSha256", sqlDigest(round.payload())).put("publicSnapshotSha256", sqlDigest(round.snapshot()));
            ArrayNode manifestArtifacts = manifest.putArray("artifacts");
            stored.forEach((id, file) -> manifestArtifacts.addObject().put("id", id).put("sha256", file.sha256())
                    .put("bytes", file.bytes()).put("uri", file.uri()));
            // A crash here leaves immutable rows and artifacts, but no read permission. An identical retry recovers sidecars.
            publish(settings.grants(), grantsBytes); publish(settings.manifest(), StrictJson.write(manifest));
            return new ImportResult(run, rounds.stream().map(Round::id).toList(), documents.size(), citations.size(), blobs.size(), Boolean.TRUE.equals(existed));
        }
    }

    /** Per-round simulation reuses the same document/evidence/round registries; no migration or operational writer. */
    private ImportResult importSimulation(byte[] sourceBytes, byte[] bundleBytes, StrictJson.Obj bundle) {
        String scope = "publication_clock_simulation", sourceSha = Canonical.sha256(sourceBytes), bundleSha = Canonical.sha256(bundleBytes);
        boolean grouped = BriefingGroupedSimulationRules.SCHEMA.equals(bundle.string("schemaVersion"));
        String run = text(bundle, "runId"), clockSha = text(bundle, "clockFileSha256");
        require(run.matches("[A-Za-z0-9_-]{1,96}") && clockSha.matches("[0-9a-f]{64}"), "simulation_identity");
        require(scope.equals(bundle.string("mode")) && sourceSha.equals(bundle.string("sourceFileSha256"))
                && bundle.bool("retrospectiveBodies") && !bundle.bool("operationalCollectionGate"), "simulation_mode");
        StrictJson.Obj authorization = bundle.object("authorization");
        require(scope.equals(authorization.string("scope")) && !authorization.bool("productionAuthorized")
                && sourceSha.equals(authorization.string("sourceSha256"))
                && (bundle.has("marketEnrichment") || settings.userInboxRef().equals(authorization.string("userInboxRef"))), "simulation_authorization");
        Map<String, StrictJson.Obj> marketRounds = validateMarketEnrichment(bundle, settings.userInboxRef(), settings.bundle().getParent());
        Map<String, Source> pool = sources(sourceBytes);
        Map<String, JsonNode> sourceNodes = new LinkedHashMap<>(); pool.forEach((key, value) -> sourceNodes.put(key, value.row().node()));
        PublicationClockRegistry clocks = new PublicationClockRegistry(settings.clocks(), sourceSha, clockSha, sourceNodes);
        BriefingGroupedSimulationRules.Archive groupedArchive = grouped
                ? BriefingGroupedSimulationRules.archive(bundle, settings.bundle().getParent(), sourceNodes, clocks) : null;
        List<StrictJson.Obj> definitions = bundle.objects("rounds"); require(definitions.size() == 14, "simulation_fourteen_rounds");
        boolean qualityV2 = simulationQualityV2(definitions.getFirst().object("identity"));
        ArrayNode noveltyHistory = StrictJson.newArray(), groupedHistory = StrictJson.newArray();
        String namespace = "brf-sim-" + Canonical.sha256(run).substring(0, 16);
        Map<String, Source> documents = new LinkedHashMap<>(); Map<String, Citation> citations = new LinkedHashMap<>();
        Map<String, Blob> blobs = new LinkedHashMap<>(); List<Round> publications = new ArrayList<>();
        List<Held> held = new ArrayList<>(); List<String> ids = new ArrayList<>();
        Map<String, JsonNode> allReceipts = simulationReceiptLedger(bundle.objects("receipts"));
        Set<String> accounted = new HashSet<>(); String priorId = null, priorSha = null;
        Instant created = pool.values().stream().map(Source::collected).max(Instant::compareTo).orElseThrow();
        for (StrictJson.Obj definition : definitions) {
            int index = ids.size(); LocalDate date = LocalDate.of(2026, 10, 2).plusDays(index / 2);
            String edition = index % 2 == 0 ? "morning" : "evening";
            String id = text(definition, "roundId"); require(id.length() <= 256 && !ids.contains(id), "simulation_round_id");
            require(date.toString().equals(definition.string("date")) && edition.equals(definition.string("edition")), "simulation_round_order");
            StrictJson.Obj window = definition.object("window");
            Instant from = ("morning".equals(edition) ? date.minusDays(1).atTime(17, 30) : date.atTime(9, 20)).atZone(KST).toInstant();
            Instant cutoff = date.atTime("morning".equals(edition) ? LocalTime.of(9, 20) : LocalTime.of(17, 30)).atZone(KST).toInstant();
            require(!window.bool("openStart") && from.equals(Instant.parse(window.string("from")))
                    && cutoff.equals(Instant.parse(window.string("to"))), "simulation_window");
            StrictJson.Obj previous = definition.object("previous");
            require("simulated_previous_output".equals(previous.string("type")), "simulation_previous_type");
            if (priorId == null) require("unavailable".equals(previous.string("status")) && !text(previous, "reason").isBlank(), "simulation_previous_unavailable");
            else require("available".equals(previous.string("status")) && priorId.equals(previous.string("roundId"))
                    && priorSha.equals(previous.string("resultSha256")), "simulation_previous_hash");
            validateSimulationIdentity(bundle, definition);
            require(simulationQualityV2(definition.object("identity")) == qualityV2, "simulation_quality_policy_drift");
            List<PublicationClockRegistry.Clock> windowClocks = clocks.verified.values().stream()
                    .filter(clock -> clock.publishedAt().isAfter(from) && !clock.publishedAt().isAfter(cutoff)).toList();
            Map<String, Source> inputs = simulationInputs(definition, pool, clocks, windowClocks);
            StrictJson.Obj coverage = definition.object("sourceCoverage");
            require(!coverage.bool("operationalCollectionGate") && coverage.count("confirmedInWindow") == windowClocks.size()
                    && coverage.count("uniqueInputCount") == inputs.size()
                    && coverage.count("excludedDuplicateCount") == windowClocks.size() - inputs.size(), "simulation_source_coverage");
            coverage.count("unconfirmedTotal");
            Map<String, JsonNode> receipts = simulationReceiptLedger(definition.objects("receipts"));
            for (var receipt : receipts.entrySet()) require(receipt.getValue().equals(allReceipts.get(receipt.getKey()))
                    && accounted.add(receipt.getKey()), "simulation_round_receipt_owner");
            Map<String, Issue> selected = selections(definition, inputs, true);
            if (grouped) BriefingGroupedSimulationRules.round(bundle, definition, groupedArchive, receipts, settings.bundle().getParent(), groupedHistory);
            if (qualityV2) {
                validateSimulationNovelty(definition, noveltyHistory, receipts);
                if (definition.has("noveltyAudit") && definition.object("noveltyAudit").bool("modelCalled"))
                    validateSimulationNoveltyRecording(definition, receipts, inputs);
            }
            String state = definition.string("selectionStatus");
            ObjectNode marker = StrictJson.newObject().put("scope", scope).put("runId", run).put("sourceFileSha256", sourceSha)
                    .put("clockFileSha256", clockSha).put("bundleSha256", bundleSha).put("userInboxRef", settings.userInboxRef())
                    .put("retrospectiveBodies", true).put("operationalCollectionGate", false)
                    .put("identitySha256", definition.string("identitySha256")).put("selectionStatus", state);
            marker.set("identity", definition.object("identity").node().deepCopy());
            marker.set("previous", previous.node().deepCopy()); marker.set("sourceCoverage", coverage.node().deepCopy());
            marker.set("clockRefs", definition.array("clockRefs").deepCopy());
            ObjectNode input = (ObjectNode) definition.node().deepCopy(); input.remove("result"); input.remove("receipts");
            blobs.put(namespace + "-input-" + index, blob("briefing_input", StrictJson.write(input)));
            documents.putAll(inputs);
            if (Set.of("HELD_SOURCE_COVERAGE", "HELD_VALIDATION").contains(state)) {
                require(selected.isEmpty() && definition.isNull("result") && definition.isNull("resultSha256"), "simulation_held_not_published");
                ObjectNode snapshot = StrictJson.newObject(); snapshot.set("replay", marker);
                held.add(new Held(id, date, edition, from, cutoff, "HELD_VALIDATION".equals(state) ? "failed" : "missing", snapshot));
                priorId = null; priorSha = null;
            } else {
                require(!inputs.isEmpty() && (("SELECTED".equals(state) && !selected.isEmpty())
                        || ("EMPTY_CONFIRMED".equals(state) && selected.isEmpty())), "simulation_selection_state");
                StrictJson.Obj result = definition.object("result"); validateGeneration(result, selected);
                require(Canonical.digest(result.node()).equals(definition.string("resultSha256")), "simulation_result_hash");
                if (!grouped) validateSimulationSuccessReceipts(edition, result, receipts, qualityV2);
                Instant generated = Instant.parse(result.string("generatedAt")); if (generated.isAfter(created)) created = generated;
                Round base = round(namespace, edition, date, date.minusDays(1), sourceSha, bundleSha, run,
                        definition.object("identity"), selected, result, inputs, generated);
                ObjectNode payload = base.payload(); payload.put("id", id);
                for (JsonNode item : payload.path("items")) {
                    Issue issue = selected.get(item.path("eventId").stringValue());
                    Instant newest = issue.citations().stream().map(citation -> clocks.verified.get(citation.source().key()).publishedAt())
                            .max(Instant::compareTo).orElseThrow();
                    ((ObjectNode) item).put("reportedAt", newest.toString()); // Document publication, not an invented event time.
                }
                payload.set("dataWindow", StrictJson.newObject().put("start", from.toString()).put("end", cutoff.toString()).put("openStart", false));
                payload.put("selectedFrom", inputs.size()); if (selected.isEmpty()) payload.put("emptyReason", "no_issues_in_window");
                ObjectNode metadata = (ObjectNode) payload.get("metadata"); metadata.put("source", "zoop-briefing-publication-clock-simulation");
                ((ObjectNode) metadata.get("selection")).put("reason", "확인된 원 발행시각을 회차 창에 나눈 과거 시뮬레이션입니다. 당시 수집·동일 본문 버전·완전한 시장 모집단을 입증하지 않습니다.");
                ArrayNode limitations = metadata.putArray("failures");
                failure(limitations, "sourceCoverage", "PUBLICATION_CLOCK_SIMULATION", "발행시각 미확인 자료 " + coverage.count("unconfirmedTotal") + "건은 제외됐으며 시장 전체 핵심 이슈를 보장하지 않습니다.");
                failure(limitations, "dataWindow", "RETROSPECTIVE_BODY", "당시 수집 기록 없이 나중 수집한 본문과 현재 관측한 publisher 발행시각을 사용합니다. 당시 본문 동일성·collection gate 통과를 주장하지 않습니다.");
                failure(limitations, "graphVersion", "SOURCE_UNAVAILABLE", "운영 권한·공개 그래프 승인이 없는 localhost 과거 시뮬레이션입니다.");
                failure(limitations, "marketVariables", "SOURCE_UNAVAILABLE", "당시 KOSPI·KOSDAQ·환율 및 실제 전망 성과를 제공하지 않습니다.");
                ObjectNode snapshot = base.snapshot(); snapshot.set("replay", marker);
                marker.put("resultSha256", definition.string("resultSha256")).put("inputArtifactId", namespace + "-input-" + index)
                        .put("resultArtifactId", namespace + "-result-" + index).put("verificationArtifactId", namespace + "-verification-" + index);
                blobs.put(namespace + "-result-" + index, blob("analysis_result", StrictJson.write(result.node())));
                blobs.put(namespace + "-verification-" + index, blob("verification_receipt", StrictJson.write(result.object("verification").node())));
                ObjectNode comparison = "morning".equals(edition) ? null : StrictJson.newObject().put("status", "unavailable")
                        .put("reason", "직전 모의 결과는 입력 문맥으로만 연결했습니다. 실제 출근 대비 장중 변화·전망 성과 평가는 없습니다.");
                Instant published = generated;
                if (marketRounds.containsKey(id)) {
                    StrictJson.Obj enrichment = marketRounds.get(id);
                    if (enrichment.has("marketContext")) {
                        List<Citation> extra = marketContextSources(enrichment, definition, pool, clocks);
                        Set<String> referenced = new HashSet<>(); for (JsonNode ref : payload.path("references").path("evidenceIds")) referenced.add(ref.stringValue());
                        Set<String> bound = new HashSet<>(); for (JsonNode binding : snapshot.path("sourceBindings")) bound.add(binding.path("documentId").stringValue());
                        for (Citation citation : extra) {
                            Citation previousCitation = citations.putIfAbsent(citation.id(), citation);
                            require(previousCitation == null || previousCitation.equals(citation), "market_context_evidence_conflict");
                            Source source = citation.source(); documents.putIfAbsent(source.key(), source);
                            if (referenced.add(citation.id())) ((ArrayNode) payload.path("references").path("evidenceIds")).add(citation.id());
                            if (bound.add(source.id())) {
                                ObjectNode binding = ((ArrayNode) snapshot.path("sourceBindings")).addObject().put("documentId", source.id())
                                        .put("documentVersion", source.version()).put("grantId", grantId(run, source)).put("grantRevision", sourceSha);
                                binding.putArray("recipients").add("openai");
                            }
                        }
                    }
                    applyMarketEnrichment(payload, snapshot, enrichment);
                    registerMarketBlobs(namespace + "-market-" + index, enrichment, blobs);
                    MarketPublicationTimes times = marketPublicationTimes(generated, enrichment);
                    generated = times.generatedAt(); published = times.publishedAt();
                    payload.put("generatedAt", generated.toString());
                    if (times.artifactCreatedAt().isAfter(created)) created = times.artifactCreatedAt();
                }
                publications.add(new Round(id, date, edition, cutoff, from, generated, published, payload, snapshot, comparison));
                for (Issue issue : selected.values()) for (Citation citation : issue.citations()) {
                    Citation prior = citations.putIfAbsent(citation.id(), citation); require(prior == null || prior.equals(citation), "simulation_evidence_conflict");
                }
                priorId = selected.isEmpty() ? null : id; priorSha = selected.isEmpty() ? null : definition.string("resultSha256");
                if (qualityV2 && "SELECTED".equals(state)) appendSimulationNoveltyHistory(noveltyHistory, definition);
                if (grouped && "SELECTED".equals(state)) for (StrictJson.Obj item : definition.objects("selected")) {
                    ObjectNode previousIssue = groupedHistory.addObject().put("issueId", item.string("issueId")).put("title", item.string("title"));
                    previousIssue.set("sources", item.array("sources").deepCopy());
                }
            }
            ids.add(id);
        }
        require(accounted.equals(allReceipts.keySet()), "simulation_unowned_paid_receipt");
        if (grouped) {
            blobs.put(namespace + "-grouped-issues", blob("briefing_input", groupedArchive.bytes()));
            for (BriefingGroupedSimulationRules.UnknownCall call : groupedArchive.unknownCalls()) {
                rejectCredentialFields(StrictJson.parseObject(call.request()).node());
                blobs.put(namespace + "-request-" + call.digest(), blob("ai_submit", call.request()));
                blobs.put(namespace + "-reservation-" + call.digest(), blob("briefing_input", call.reservation()));
            }
            ObjectNode accounting = StrictJson.newObject().put("unknownGroupingCalls", groupedArchive.unknownCalls().size())
                    .put("allGroupingUsageKnown", groupedArchive.root().objects("receipts").stream().allMatch(r -> r.bool("usageKnown")));
            accounting.put("meaning", "Unknown reservations retain no fabricated usage or provider response and are never selected evidence.");
            blobs.put(namespace + "-grouping-accounting", blob("verification_receipt", StrictJson.write(accounting)));
            for (var receipt : simulationReceiptLedger(bundle.objects("groupingReceipts")).entrySet())
                require(allReceipts.putIfAbsent(receipt.getKey(), receipt.getValue()) == null, "grouped_receipt_ownership");
        }
        if (bundle.has("marketEnrichment")) for (var receipt : simulationReceiptLedger(bundle.object("marketEnrichment").objects("receipts")).entrySet())
            require(allReceipts.putIfAbsent(receipt.getKey(), receipt.getValue()) == null, "market_enrichment_receipt_reuses_news_request");
        if (bundle.has("marketEnrichment") && bundle.object("marketEnrichment").has("comparisonBaselineSha256")) {
            StrictJson.Obj layer = bundle.object("marketEnrichment"); Path output = settings.bundle().getParent();
            byte[] priorBytes = read(output.resolve("market/baselines/" + layer.string("comparisonBaselineSha256") + ".json"));
            StrictJson.Obj prior = StrictJson.parseObject(priorBytes);
            blobs.put(namespace + "-comparison-baseline", blob("briefing_input", priorBytes));
            blobs.put(namespace + "-frozen-preview", blob("briefing_input", read(output.resolve("market/previews/" + layer.string("frozenPreviewSha256") + ".json"))));
            for (var receipt : simulationReceiptLedger(prior.object("marketEnrichment").objects("receipts")).entrySet())
                require(allReceipts.putIfAbsent(receipt.getKey(), receipt.getValue()) == null, "comparison_receipt_duplicate");
        }
        blobs.put(namespace + "-bundle", blob("ai_submit", bundleBytes));
        blobs.put(namespace + "-clocks", blob("verification_receipt", clocks.bytes));
        clocks.html.forEach((sha, content) -> blobs.put(namespace + "-html-" + sha.substring(0, 24), new Blob("raw_document", content, "text/html; charset=utf-8")));
        sourceBlobs(namespace, sourceSha, documents, citations, blobs);
        int receiptIndex = 0; for (JsonNode receipt : allReceipts.values()) blobs.put(namespace + "-usage-" + receiptIndex++, blob("ai_call_receipt", StrictJson.write(receipt)));
        paidResponseBlobs(namespace, allReceipts, blobs);
        ObjectNode grants = grants(run, sourceSha, documents.values().stream().toList()); grants.put("scope", scope);
        byte[] grantBytes = StrictJson.write(grants); checkExisting(settings.grants(), grantBytes);
        if (Files.exists(settings.manifest(), LinkOption.NOFOLLOW_LINKS)) {
            StrictJson.Obj prior = StrictJson.parseObject(read(settings.manifest()));
            require(scope.equals(prior.string("scope")) && run.equals(prior.string("runId"))
                    && bundleSha.equals(prior.string("bundleSha256")) && clockSha.equals(prior.string("clockFileSha256")), "simulation_manifest_conflict");
        }
        Instant storedAt = created;
        try (ArtifactFileStore.Session files = ArtifactFileStore.at(settings.artifactRoot()).open()) {
            Map<String, ArtifactFileStore.StoredFile> stored = new LinkedHashMap<>();
            blobs.forEach((id, value) -> stored.put(id, files.put("briefing_replay", id + ".bin", value.bytes())));
            Boolean existed = transaction.execute(status -> {
                jdbc.execute("SELECT pg_advisory_xact_lock(hashtext('briefing_development_replay'))");
                int count = 0; for (String id : ids) count += jdbc.queryForObject("SELECT count(*) FROM briefing_rounds WHERE id=?", Integer.class, id);
                require(count == 0 || count == ids.size(), "simulation_partial_run_conflict");
                blobs.forEach((id, value) -> register(id, value, stored.get(id), storedAt));
                documents.forEach((key, value) -> registerDocument(namespace, value, clocks.verified.get(key).publishedAt()));
                citations.values().forEach(value -> registerEvidence(namespace, value, storedAt));
                publications.forEach(this::registerRound); held.forEach(value -> registerHeld(value, storedAt));
                return count == ids.size();
            });
            ObjectNode manifest = StrictJson.newObject().put("schemaVersion", "zoop-briefing-replay-manifest-v1").put("scope", scope)
                    .put("runId", run).put("sourceFileSha256", sourceSha).put("clockFileSha256", clockSha).put("bundleSha256", bundleSha)
                    .put("userInboxRef", settings.userInboxRef()).put("grantsSha256", Canonical.sha256(grantBytes));
            ArrayNode summaries = manifest.putArray("rounds");
            for (String id : ids) {
                Round published = publications.stream().filter(row -> row.id().equals(id)).findFirst().orElse(null);
                if (published != null) summaries.addObject().put("id", id).put("payloadSha256", sqlDigest(published.payload()))
                        .put("publicSnapshotSha256", sqlDigest(published.snapshot()));
                else { Held withheld = held.stream().filter(row -> row.id().equals(id)).findFirst().orElseThrow();
                    summaries.addObject().put("id", id).putNull("payloadSha256").put("publicSnapshotSha256", sqlDigest(withheld.snapshot())); }
            }
            ArrayNode artifactList = manifest.putArray("artifacts"); stored.forEach((id, value) -> artifactList.addObject().put("id", id)
                    .put("sha256", value.sha256()).put("bytes", value.bytes()).put("uri", value.uri()));
            publish(settings.grants(), grantBytes); publish(settings.manifest(), StrictJson.write(manifest));
            return new ImportResult(run, List.copyOf(ids), documents.size(), citations.size(), blobs.size(), Boolean.TRUE.equals(existed));
        }
    }

    /** Independently restore every broad-input span from the source/clock registry before any DB write. */
    private static List<Citation> marketContextSources(StrictJson.Obj record, StrictJson.Obj definition,
            Map<String, Source> pool, PublicationClockRegistry clocks) {
        StrictJson.Obj context = record.object("marketContext");
        require("zoop-briefing-market-context-v1".equals(context.string("schemaVersion"))
                && "publication_clock_simulation".equals(context.string("scope")) && !context.bool("operationalCollectionGate")
                && context.object("window").node().equals(definition.object("window").node()), "market_context_schema_window");
        for (String field : List.of("roundId", "date", "edition"))
            require(context.string(field).equals(definition.string(field)), "market_context_round");
        Instant from = Instant.parse(definition.object("window").string("from")), cutoff = Instant.parse(record.string("cutoff"));
        Map<String, Source> expected = new LinkedHashMap<>(); Set<String> bodies = new HashSet<>();
        for (PublicationClockRegistry.Clock clock : clocks.verified.values().stream()
                .sorted(java.util.Comparator.comparing(PublicationClockRegistry.Clock::documentId)).toList()) {
            if (clock.publishedAt().isAfter(cutoff)) continue;
            String role = clock.publishedAt().isAfter(from) ? "new" : "background";
            if (bodies.add(role + "\u0000" + clock.bodySha256())) expected.put(clock.documentId(), pool.get(clock.key()));
        }
        require(expected.size() <= 1000, "market_context_population");
        Set<String> actual = new HashSet<>(), companyNames = new java.util.TreeSet<>(); List<Citation> citations = new ArrayList<>();
        int fresh = 0;
        for (StrictJson.Obj card : context.objects("documents")) {
            String document = text(card, "documentId"); Source source = expected.get(document);
            require(actual.add(document) && source != null && source.version().equals(card.string("documentVersion"))
                    && source.bodySha().equals(card.string("bodySha256")), "market_context_source_binding");
            PublicationClockRegistry.Clock clock = clocks.verified.get(source.key());
            String role = clock.publishedAt().isAfter(from) ? "new" : "background";
            require(role.equals(card.string("role")), "market_context_source_role"); if ("new".equals(role)) fresh++;
            Set<String> names = new java.util.TreeSet<>();
            if (source.row().has("companyAssociations")) for (JsonNode value : source.row().array("companyAssociations"))
                if (value.isObject() && value.path("companyName").isString() && !value.path("companyName").stringValue().isBlank())
                    names.add(value.path("companyName").stringValue());
            if (source.row().has("companyName") && !source.row().isNull("companyName")) {
                String name = source.row().string("companyName"); if (!name.isBlank()) names.add(name);
            }
            require(card.strings("companyNames").equals(List.copyOf(names)), "market_context_company_binding"); companyNames.addAll(names);
            int length = source.body().codePointCount(0, source.body().length());
            List<StrictJson.Obj> spans = card.objects("sources"); require(spans.size() == (length > 900 ? 2 : 1), "market_context_span_coverage");
            for (int index = 0; index < spans.size(); index++) {
                StrictJson.Obj span = spans.get(index); int start = index == 0 ? 0 : length - 300;
                int end = index == 0 ? Math.min(600, length) : length;
                String exact = source.body().substring(source.body().offsetByCodePoints(0, start), source.body().offsetByCodePoints(0, end));
                require(document.equals(span.string("documentId")) && source.version().equals(span.string("documentVersion"))
                        && source.bodySha().equals(span.string("bodySha256")) && start == span.count("start") && end == span.count("end")
                        && "unicode_code_point".equals(span.string("offsetUnit")) && exact.equals(span.string("quote"))
                        && clock.publishedAt().equals(Instant.parse(span.string("publishedAt"))), "market_context_exact_span");
                ObjectNode identity = StrictJson.newObject().put("documentId", document).put("bodySha256", source.bodySha()).put("start", start).put("end", end);
                require(("market-evidence-" + Canonical.digest(identity).substring(0, 32)).equals(span.string("evidenceId")), "market_context_evidence_id");
                citations.add(new Citation(span.string("evidenceId"), source, exact, start, end));
            }
        }
        require(actual.equals(expected.keySet()), "market_context_complete_source_coverage");
        StrictJson.Obj coverage = context.object("coverage");
        require(coverage.count("documents") == actual.size() && coverage.count("newDocuments") == fresh
                && coverage.count("backgroundDocuments") == actual.size() - fresh
                && coverage.strings("companyNames").equals(List.copyOf(companyNames))
                && coverage.count("unconfirmedTotal") == definition.object("sourceCoverage").count("unconfirmedTotal")
                && !coverage.bool("sectorPriceFeedAvailable") && !coverage.bool("marketRepresentative")
                && !coverage.bool("historicalBodyUnchangedProven") && "exact_prefix600_suffix300".equals(coverage.string("bodyScope")), "market_context_coverage");
        return citations;
    }

    /** Add-on artifacts preserve every original news identity/result and are imported into a separate replay DB. */
    static Map<String, StrictJson.Obj> validateMarketEnrichment(StrictJson.Obj bundle, String userInboxRef, Path output) {
        Map<String, StrictJson.Obj> result = new LinkedHashMap<>();
        if (!bundle.has("marketEnrichment")) return result;
        StrictJson.Obj layer = bundle.object("marketEnrichment");
        require("zoop-briefing-market-enrichment-v1".equals(layer.string("schemaVersion"))
                && "raw-json-sha256-v1".equals(layer.string("digestScheme"))
                && userInboxRef.equals(layer.string("userInboxRef")), "market_enrichment_authorization");
        ObjectNode baseline = (ObjectNode) bundle.node().deepCopy(); baseline.remove("marketEnrichment");
        require(Canonical.digest(baseline).equals(layer.string("baselineBundleSha256")), "market_enrichment_baseline_hash");
        Map<String, StrictJson.Obj> published = new LinkedHashMap<>();
        for (StrictJson.Obj round : bundle.objects("rounds")) if ("SELECTED".equals(round.string("selectionStatus")))
            require(published.putIfAbsent(round.string("roundId"), round) == null, "market_enrichment_duplicate_news_round");
        List<StrictJson.Obj> comparison = layer.objects("rounds");
        Map<String, StrictJson.Obj> prepared = new LinkedHashMap<>();
        boolean frozen = layer.has("comparisonBaselineSha256");
        if (frozen) {
            String sha = layer.string("comparisonBaselineSha256"); require(sha.matches("[0-9a-f]{64}"), "comparison_baseline_sha");
            byte[] raw = read(output.resolve("market/baselines/" + sha + ".json"));
            StrictJson.Obj prior = StrictJson.parseObject(raw);
            require(Canonical.sha256(raw).equals(sha) && prior.has("marketEnrichment")
                    && !prior.object("marketEnrichment").has("comparisonBaselineSha256"), "comparison_baseline_artifact");
            ObjectNode priorNews = (ObjectNode) prior.node().deepCopy(); priorNews.remove("marketEnrichment");
            require(priorNews.equals(baseline), "comparison_baseline_news_binding");
            // Validate the actual old model receipts/artifacts before using that exact previous version.
            comparison = List.copyOf(validateMarketEnrichment(prior, prior.object("marketEnrichment").string("userInboxRef"), output).values());
            String previewSha = layer.string("frozenPreviewSha256"); require(previewSha.matches("[0-9a-f]{64}"), "frozen_preview_sha");
            byte[] previewRaw = read(output.resolve("market/previews/" + previewSha + ".json"));
            StrictJson.Obj preview = StrictJson.parseObject(previewRaw);
            require(Canonical.sha256(previewRaw).equals(previewSha) && sha.equals(preview.string("baselineBundleSha256"))
                    && "zoop-market-context-preview-v1".equals(preview.string("schemaVersion"))
                    && userInboxRef.equals(preview.string("userInboxRef"))
                    && layer.string("executionAuthorizationRef").matches("inbox/[A-Za-z0-9_.-]+\\.md"), "frozen_preview_binding");
            for (StrictJson.Obj row : preview.objects("rounds")) require(prepared.putIfAbsent(row.string("roundId"), row) == null, "frozen_preview_duplicate");
            require(prepared.keySet().equals(published.keySet()), "frozen_preview_population");
        }
        Map<String, JsonNode> all = simulationReceiptLedger(layer.objects("receipts")); Set<String> accounted = new HashSet<>();
        for (StrictJson.Obj record : layer.objects("rounds")) {
            String id = record.string("roundId"); StrictJson.Obj news = published.get(id);
            require(news != null && result.putIfAbsent(id, record) == null, "market_enrichment_round_scope");
            validateMarketRecord(record, news, userInboxRef, output);
            if (record.has("marketContext")) BriefingMarketContextRules.previous(record, comparison);
            require(frozen == record.has("frozenExecution"), "frozen_execution_mode");
            if (frozen) {
                require(record.has("marketContext") && !record.isNull("summaryResult"), "frozen_context_required");
                StrictJson.Obj binding = record.object("frozenExecution"), row = prepared.get(id), summary = record.object("summaryResult");
                for (String field : List.of("comparisonBaselineSha256", "executionAuthorizationRef"))
                    require(layer.string(field).equals(binding.string(field)), "frozen_execution_binding");
                String digest = row.string("requestSha256");
                require(layer.string("frozenPreviewSha256").equals(binding.string("previewSha256"))
                        && digest.equals(binding.string("preparedRequestSha256"))
                        && !summary.objects("attempts").isEmpty()
                        && digest.equals(summary.objects("attempts").getFirst().string("generationRequestDigest"))
                        && all.containsKey(digest) && "market_summary_generation".equals(StrictJson.Obj.of(all.get(digest)).string("stage")), "frozen_prepared_first_call");
                byte[] request = read(output.resolve("calls/" + digest + ".request.json"));
                require(Canonical.sha256(request).equals(digest) && request.length == row.count("requestBytes"), "frozen_prepared_request_bytes");
                StrictJson.Obj first = StrictJson.parseObject(StrictJson.parseObject(request).string("input"));
                require(first.object("marketContext").node().equals(record.object("marketContext").node())
                        && first.object("context").node().equals(record.object("context").node())
                        && first.string("frozenInputSha256").equals(summary.string("frozenInputSha256")), "frozen_prepared_input_binding");
            }
            for (var receipt : simulationReceiptLedger(record.objects("receipts")).entrySet())
                require(receipt.getValue().equals(all.get(receipt.getKey())) && accounted.add(receipt.getKey()), "market_enrichment_receipt_owner");
        }
        require(result.keySet().equals(published.keySet()) && accounted.equals(all.keySet()), "market_enrichment_round_or_receipt_coverage");
        return result;
    }

    static void validateMarketRecord(StrictJson.Obj record, StrictJson.Obj news, String inbox, Path output) {
        require(news.string("roundId").equals(record.string("roundId")) && news.string("date").equals(record.string("date"))
                && news.string("edition").equals(record.string("edition"))
                && news.object("window").string("to").equals(record.string("cutoff"))
                && news.string("resultSha256").equals(record.string("newsResultSha256")), "market_enrichment_news_binding");
        StrictJson.Obj snapshot = record.object("marketSnapshot");
        marketArtifact(output, "snapshots", record.string("marketSnapshotSha256"), snapshot.node());
        validateMarketSnapshot(snapshot, record);
        validateMarketRawValues(snapshot, output);
        StrictJson.Obj context = record.object("context").keys(Set.of("roundId", "date", "edition", "cutoff", "newsResultSha256", "marketSnapshotSha256", "userInboxRef"), Set.of("promptArtifacts", "marketContextSha256", "summaryPromptVersion"));
        require(Canonical.digest(context.node()).equals(record.string("contextSha256")) && inbox.equals(context.string("userInboxRef")), "market_enrichment_context_hash");
        if (context.has("promptArtifacts")) {
            StrictJson.Obj prompts = context.object("promptArtifacts").exactly(Set.of("generation.md", "generation.schema.json", "verification.md", "verification.schema.json"));
            String folder = record.has("marketContext") ? "market-context" : "market-summary";
            for (String name : prompts.node().propertyNames()) try (var stream = BriefingReplayImporter.class.getResourceAsStream("/briefing/prompts/" + folder + "/" + name)) {
                require(stream != null && Canonical.sha256(stream.readAllBytes()).equals(prompts.string(name)), "market_enrichment_prompt_hash");
            } catch (IOException error) { throw new IllegalArgumentException("Market summary prompt unavailable", error); }
        }
        for (String key : List.of("roundId", "date", "edition", "cutoff", "newsResultSha256", "marketSnapshotSha256"))
            require(record.string(key).equals(context.string(key)), "market_enrichment_context_binding");
        for (StrictJson.Obj raw : snapshot.objects("rawRefs")) {
            byte[] bytes = marketRaw(output, raw.string("sha256"));
            require(bytes.length == raw.count("bytes"), "market_enrichment_raw_size");
        }
        Map<String, JsonNode> receipts = simulationReceiptLedger(record.objects("receipts"));
        for (JsonNode value : receipts.values()) {
            StrictJson.Obj receipt = StrictJson.Obj.of(value);
            require(Set.of("market_summary_generation", "market_summary_verification").contains(receipt.string("stage")), "market_enrichment_receipt_stage");
            if (!receipt.bool("usageKnown")) require(receipt.isNull("inputTokens") && receipt.isNull("outputTokens"), "market_enrichment_unknown_usage_null");
        }
        if (record.isNull("summaryResult")) {
            require(record.isNull("summaryResultSha256"), "market_enrichment_absent_result_hash"); return;
        }
        StrictJson.Obj summary = record.object("summaryResult");
        marketArtifact(output, "summaries", record.string("summaryResultSha256"), summary.node());
        if (record.has("marketContext")) {
            StrictJson.Obj broad = record.object("marketContext");
            require(BriefingMarketContextRules.contextual(summary) && "market-context-v2".equals(context.string("summaryPromptVersion"))
                    && context.string("marketContextSha256").equals(summary.string("marketContextSha256")), "market_context_digest_binding");
            marketArtifact(output, "contexts", context.string("marketContextSha256"), broad.node());
            BriefingMarketContextRules.targetsAndEvaluations(broad, snapshot);
            validateMarketSummary(summary, news, snapshot, broad);
        } else {
            require(!BriefingMarketContextRules.contextual(summary), "market_context_result_without_input");
            validateMarketSummary(summary, news, snapshot);
        }
        if (!summary.objects("claims").isEmpty()) validateMarketSummaryRecordings(record, news, receipts, output);
    }

    static Set<String> validateMarketSnapshot(StrictJson.Obj snapshot, StrictJson.Obj record) {
        require("zoop-briefing-market-snapshot-v1".equals(snapshot.string("schemaVersion"))
                && "historical_snapshot".equals(snapshot.string("scope")) && !snapshot.bool("operationalCollectionGate"), "market_snapshot_schema");
        for (String key : List.of("date", "edition", "cutoff")) require(record.string(key).equals(snapshot.object("round").string(key)), "market_snapshot_round_binding");
        Instant cutoff = Instant.parse(record.string("cutoff")); LocalDate cutoffDate = cutoff.atZone(KST).toLocalDate();
        Instant fetched = Instant.parse(snapshot.string("fetchedAt")); StrictJson.Obj variables = snapshot.object("marketVariables");
        require("available".equals(variables.string("status")) && cutoff.equals(Instant.parse(variables.string("referenceAt")))
                && !Instant.parse(variables.string("rateCutoffAt")).isAfter(cutoff)
                && fetched.equals(Instant.parse(variables.string("collectedAt"))), "market_snapshot_cutoff");
        Set<String> ids = new HashSet<>(), available = new HashSet<>(), backed = new HashSet<>();
        for (StrictJson.Obj raw : snapshot.objects("rawRefs")) {
            require(raw.string("sha256").matches("[0-9a-f]{64}") && (raw.count("bytes") > 0
                    || (raw.has("httpStatus") && raw.count("httpStatus") != 200)), "market_snapshot_raw_ref");
            text(raw, "source"); require(raw.string("url").startsWith("https://"), "market_snapshot_raw_url");
            for (String id : raw.strings("indicatorIds")) require(Set.of("kospi", "kosdaq", "usdkrw").contains(id) && backed.add(id), "market_snapshot_raw_indicator");
        }
        for (StrictJson.Obj indicator : variables.objects("indicators")) {
            String id = indicator.string("id"), status = indicator.string("status");
            require(Set.of("kospi", "kosdaq", "usdkrw").contains(id) && ids.add(id)
                    && ("usdkrw".equals(id) ? "KRW" : "pt").equals(indicator.string("unit"))
                    && Set.of("ok", "delayed", "unavailable", "failed").contains(status), "market_indicator_identity");
            text(indicator, "label");
            for (String key : List.of("value", "change", "changeRate")) require(indicator.isNull(key)
                    || (indicator.raw(key).isNumber() && Double.isFinite(indicator.raw(key).doubleValue())), "market_indicator_number");
            if (!indicator.isNull("observedAt")) require(!Instant.parse(indicator.string("observedAt")).isAfter(cutoff), "market_indicator_future_observation");
            if (!indicator.isNull("observedDate")) require(!LocalDate.parse(indicator.string("observedDate")).isAfter(cutoffDate), "market_indicator_future_date");
            if (Set.of("ok", "delayed").contains(status)) {
                require(!indicator.isNull("value") && !indicator.isNull("observedDate") && !indicator.isNull("source")
                        && Set.of("close", "latest", "reference").contains(indicator.string("valueKind")) && backed.contains(id), "market_indicator_available_binding");
                require(!"reference".equals(indicator.string("valueKind")) || "usdkrw".equals(id), "market_reference_indicator_identity");
                if (indicator.isNull("observedAt")) require(Set.of("close", "reference").contains(indicator.string("valueKind"))
                        && (!LocalDate.parse(indicator.string("observedDate")).equals(cutoffDate) || !cutoff.atZone(KST).toLocalTime().isBefore(LocalTime.of(15, 30))), "market_indicator_unavailable_same_day_close");
                StrictJson.Obj source = indicator.object("source");
                require(Set.of("yahoo", "naver", "toss").contains(source.string("provider")), "market_indicator_provider");
                text(source, "name"); text(source, "symbol"); source.bool("official"); source.stringOrNull("delayNote"); source.stringOrNull("url");
                available.add(id);
            } else require(indicator.isNull("value") && indicator.isNull("change") && indicator.isNull("changeRate")
                    && !text(indicator, "reason").isBlank(), "market_indicator_unavailable_not_zero");
            if (!indicator.isNull("baseline")) {
                StrictJson.Obj baseline = indicator.object("baseline");
                require(baseline.raw("value").isNumber() && Double.isFinite(baseline.raw("value").doubleValue())
                        && !LocalDate.parse(baseline.string("date")).isAfter(cutoffDate), "market_indicator_baseline");
                String at = baseline.stringOrNull("at"); if (at != null && at.contains("T")) require(!Instant.parse(at).isAfter(cutoff), "market_indicator_future_baseline");
            }
            indicator.stringOrNull("reason"); indicator.stringOrNull("reasonCode");
        }
        require(ids.equals(Set.of("kospi", "kosdaq", "usdkrw")), "market_snapshot_three_indicators");
        return available;
    }

    /** Daily bar timestamps identify rows; they are never presented as the close's observation timestamp. */
    static void validateMarketRawValues(StrictJson.Obj snapshot, Path output) {
        StrictJson.Obj normalization = snapshot.object("normalization");
        require("decimal-half-up-2dp".equals(normalization.string("values"))
                && "difference-of-normalized-values".equals(normalization.string("change"))
                && "change/baseline".equals(normalization.string("changeRate")), "market_normalization_policy");
        Map<String, StrictJson.Obj> indicators = new LinkedHashMap<>(), refs = new LinkedHashMap<>();
        for (StrictJson.Obj value : snapshot.object("marketVariables").objects("indicators"))
            if (Set.of("ok", "delayed").contains(value.string("status"))) indicators.put(value.string("id"), value);
        for (StrictJson.Obj ref : snapshot.objects("rawRefs")) refs.put(ref.string("sha256"), ref);
        Instant cutoff = Instant.parse(snapshot.object("round").string("cutoff")); Set<String> bound = new HashSet<>();
        for (StrictJson.Obj binding : snapshot.objects("indicatorBindings")) {
            String id = binding.string("id"), sha = binding.string("rawSha256"); StrictJson.Obj indicator = indicators.get(id), ref = refs.get(sha);
            require(indicator != null && bound.add(id) && ref != null && ref.strings("indicatorIds").contains(id), "market_raw_binding_identity");
            byte[] raw = marketRaw(output, sha); int selectedIndex = binding.count("sourceRowIndex");
            Map<LocalDate, java.math.BigDecimal> values = new LinkedHashMap<>(); List<LocalDate> rowDates = new ArrayList<>();
            boolean fx = "usdkrw".equals(id);
            if (fx) {
                require("day".equals(binding.string("precision")) && "closePrice".equals(binding.string("field"))
                        && "naver".equals(indicator.object("source").string("provider")), "market_fx_raw_format");
                StrictJson.Obj list = StrictJson.parseObject("{\"rows\":" + new String(raw, StandardCharsets.UTF_8) + "}");
                for (StrictJson.Obj row : list.objects("rows")) {
                    LocalDate date = LocalDate.parse(row.string("localTradedAt")); rowDates.add(date);
                    java.math.BigDecimal value;
                    try { value = new java.math.BigDecimal(row.string("closePrice").replace(",", "")).setScale(2, java.math.RoundingMode.HALF_UP); }
                    catch (NumberFormatException error) { throw new IllegalArgumentException("market_fx_raw_number", error); }
                    require(values.putIfAbsent(date, value) == null, "market_raw_duplicate_date");
                }
            } else {
                require("session_close".equals(binding.string("precision")) && "close".equals(binding.string("field"))
                        && "yahoo".equals(indicator.object("source").string("provider")), "market_index_raw_format");
                List<StrictJson.Obj> results = StrictJson.parseObject(raw).object("chart").objects("result"); require(results.size() == 1, "market_yahoo_result_count");
                StrictJson.Obj feed = results.getFirst(); require(("kospi".equals(id) ? "^KS11" : "^KQ11").equals(feed.object("meta").string("symbol")), "market_yahoo_symbol");
                JsonNode stamps = feed.array("timestamp"), closes = feed.object("indicators").objects("quote").getFirst().array("close");
                require(stamps.size() == closes.size(), "market_yahoo_row_coverage");
                for (int index = 0; index < stamps.size(); index++) {
                    JsonNode stamp = stamps.get(index), close = closes.get(index);
                    require(stamp.isIntegralNumber() && stamp.canConvertToLong(), "market_yahoo_timestamp");
                    LocalDate date = Instant.ofEpochSecond(stamp.longValue()).atZone(KST).toLocalDate(); rowDates.add(date);
                    if (close.isNull()) continue;
                    require(close.isNumber() && Double.isFinite(close.doubleValue()), "market_yahoo_raw_number");
                    require(values.putIfAbsent(date, close.decimalValue().setScale(2, java.math.RoundingMode.HALF_UP)) == null, "market_raw_duplicate_date");
                }
            }
            LocalDate sourceDate = LocalDate.parse(binding.string("sourceDate"));
            require(selectedIndex < rowDates.size() && sourceDate.equals(rowDates.get(selectedIndex))
                    && sourceDate.toString().equals(indicator.string("observedDate")) && values.containsKey(sourceDate)
                    && ("close".equals(indicator.string("valueKind")) || (fx && "reference".equals(indicator.string("valueKind"))))
                    && indicator.isNull("observedAt"), "market_raw_selected_row");
            Instant upper = marketUpperBound(sourceDate, fx);
            require(upper.equals(Instant.parse(binding.string("availabilityUpperBound"))) && !upper.isAfter(cutoff), "market_raw_future_availability");
            LocalDate latest = values.keySet().stream().filter(date -> !marketUpperBound(date, fx).isAfter(cutoff)).max(LocalDate::compareTo).orElseThrow();
            require(latest.equals(sourceDate) && values.get(sourceDate).compareTo(indicator.raw("value").decimalValue()) == 0, "market_raw_value_or_latest_row");
            LocalDate previous = values.keySet().stream().filter(date -> date.isBefore(sourceDate)).max(LocalDate::compareTo).orElse(null);
            if (previous == null) require(indicator.isNull("baseline") && indicator.isNull("change") && indicator.isNull("changeRate"), "market_raw_absent_baseline");
            else {
                StrictJson.Obj baseline = indicator.object("baseline"); java.math.BigDecimal baselineValue = values.get(previous);
                require(previous.toString().equals(baseline.string("date")) && baselineValue.compareTo(baseline.raw("value").decimalValue()) == 0, "market_raw_baseline_value");
                java.math.BigDecimal change = values.get(sourceDate).subtract(baselineValue);
                require(!indicator.isNull("change") && Math.abs(change.doubleValue() - indicator.raw("change").doubleValue()) <= 1e-9, "market_raw_change");
                if (baselineValue.signum() == 0) require(indicator.isNull("changeRate"), "market_raw_zero_baseline_rate");
                else require(!indicator.isNull("changeRate") && Math.abs(change.doubleValue() / baselineValue.doubleValue() - indicator.raw("changeRate").doubleValue()) <= 1e-9, "market_raw_change_rate");
            }
        }
        require(bound.equals(indicators.keySet()), "market_raw_binding_coverage");
    }

    private static Instant marketUpperBound(LocalDate date, boolean fx) {
        return fx ? date.plusDays(1).atStartOfDay(KST).toInstant() : date.atTime(15, 30).atZone(KST).toInstant();
    }

    static void validateMarketSummary(StrictJson.Obj summary, StrictJson.Obj news, StrictJson.Obj snapshot) {
        validateMarketSummary(summary, news, snapshot, null);
    }

    static void validateMarketSummary(StrictJson.Obj summary, StrictJson.Obj news, StrictJson.Obj snapshot, StrictJson.Obj broad) {
        boolean contextual = broad != null;
        Instant.parse(summary.string("generatedAt")); text(summary, "scopeNote");
        Set<String> evidence = new HashSet<>(); for (StrictJson.Obj selected : news.objects("selected"))
            for (StrictJson.Obj source : selected.objects("sources")) evidence.add(source.string("evidenceId"));
        Set<String> indicators = new HashSet<>(); for (StrictJson.Obj indicator : snapshot.object("marketVariables").objects("indicators"))
            if (Set.of("ok", "delayed").contains(indicator.string("status"))) indicators.add(indicator.string("id"));
        if (contextual) evidence.addAll(BriefingMarketContextRules.evidence(broad));
        List<String> texts = new ArrayList<>(); Set<String> targets = new HashSet<>(), citedNews = new HashSet<>();
        List<StrictJson.Obj> claims = summary.objects("claims");
        String status = summary.object("verification").string("status");
        require(Set.of("PASS", "WITHHELD").contains(status), "market_summary_verification_status");
        if (claims.isEmpty() && "WITHHELD".equals(status)) {
            require(summary.isNull("text") && summary.isNull("summary") && summary.isNull("resultVersion"), "market_summary_withheld_content"); return;
        }
        require(claims.size() >= 2 && claims.size() <= (contextual ? 8 : 4), "market_summary_claim_count");
        for (int index = 0; index < claims.size(); index++) {
            StrictJson.Obj claim = claims.get(index); texts.add(text(claim, "text"));
            List<String> refs = claim.strings("evidenceIds"), ids = claim.strings("indicatorIds");
            boolean previousBasis = contextual && (!claim.strings("previousForecastIds").isEmpty() || !claim.strings("evaluationIds").isEmpty() || !claim.strings("previousPublicationIds").isEmpty());
            require((!refs.isEmpty() || !ids.isEmpty() || previousBasis) && evidence.containsAll(refs) && indicators.containsAll(ids)
                    && new HashSet<>(refs).size() == refs.size() && new HashSet<>(ids).size() == ids.size(), "market_summary_foreign_reference");
            String claimId = "market:claim:" + index; require(claimId.equals(claim.string("claimId")), "market_summary_claim_id");
            citedNews.addAll(refs); targets.add(claimId);
        }
        texts.add(summary.string("scopeNote"));
        if ("PASS".equals(status)) require(String.join("\n", texts).equals(summary.string("text")), "market_summary_unverified_text");
        else require(summary.isNull("text") && summary.isNull("summary") && summary.isNull("resultVersion"), "market_summary_withheld_content");
        StrictJson.Obj verification = summary.object("verification");
        Set<String> checked = new HashSet<>(); boolean supported = true;
        for (StrictJson.Obj check : verification.objects("checks")) {
            require(checked.add(text(check, "targetId")) && Set.of("SUPPORTED", "UNSUPPORTED", "UNCERTAIN").contains(check.string("verdict")), "market_summary_check_identity");
            supported &= "SUPPORTED".equals(check.string("verdict")) && check.bool("noUnsupportedNumbers")
                    && check.bool("noUnsupportedCausality") && check.bool("temporalAppropriate") && check.bool("noInvestmentAdvice")
                    && (!contextual || (check.bool("comparisonAppropriate") && check.bool("forecastAppropriate"))); text(check, "reason");
        }
        if (contextual) BriefingMarketContextRules.claims(summary, broad);
        require(checked.equals(targets) && ("PASS".equals(status) == supported), "market_summary_verification_coverage");
        if ("PASS".equals(status)) require(!citedNews.isEmpty(), "market_summary_news_evidence_required");
    }

    private static void validateMarketSummaryRecordings(StrictJson.Obj record, StrictJson.Obj news, Map<String, JsonNode> receipts, Path output) {
        StrictJson.Obj summary = record.object("summaryResult");
        for (String field : List.of("generationRequestDigest", "verificationRequestDigest")) {
            String digest = summary.string(field); JsonNode node = receipts.get(digest); require(node != null, "market_summary_final_receipt_missing");
            StrictJson.Obj receipt = StrictJson.Obj.of(node); String stage = "generationRequestDigest".equals(field)
                    ? "market_summary_generation" : "market_summary_verification";
            require(stage.equals(receipt.string("stage")) && success(receipt) && receipt.bool("usageKnown") && receipt.count("httpStatus") == 200, "market_summary_final_receipt_failed");
            byte[] requestBytes = read(output.resolve("calls").resolve(digest + ".request.json"));
            require(digest.equals(Canonical.sha256(requestBytes)), "market_summary_request_hash");
            StrictJson.Obj request = StrictJson.parseObject(requestBytes), data = StrictJson.parseObject(request.string("input"));
            require(stage.equals(request.object("text").object("format").string("name"))
                    && receipt.string("model").equals(request.string("model"))
                    && record.string("contextSha256").equals(data.string("contextSha256"))
                    && record.object("context").node().equals(data.object("context").node())
                    && record.object("marketSnapshot").node().equals(data.object("marketSnapshot").node())
                    && news.array("selected").equals(data.array("selected"))
                    && news.object("result").array("items").equals(data.array("newsItems")), "market_summary_request_context");
            if (record.has("marketContext")) {
                require(record.object("marketContext").node().equals(data.object("marketContext").node())
                        && summary.string("frozenInputSha256").equals(data.string("frozenInputSha256")), "market_context_recording_binding");
                ObjectNode frozen = (ObjectNode) data.node().deepCopy();
                frozen.remove(List.of("frozenInputSha256", "repairAttempt", "priorDraft", "priorValidation", "draft"));
                marketArtifact(output, "frozen-inputs", summary.string("frozenInputSha256"), frozen);
            }
            byte[] responseBytes = read(output.resolve("calls").resolve(digest + ".response.json"));
            require(Canonical.sha256(responseBytes).equals(receipt.string("responseSha256")), "market_summary_response_hash");
            StrictJson.Obj response = StrictJson.parseObject(responseBytes); List<String> texts = new ArrayList<>();
            require(receipt.string("status").equals(response.string("status")) && receipt.string("responseId").equals(response.string("id"))
                    && receipt.count("inputTokens") == response.object("usage").count("input_tokens")
                    && receipt.count("outputTokens") == response.object("usage").count("output_tokens"), "market_summary_response_usage");
            for (StrictJson.Obj message : response.objects("output")) if ("message".equals(message.string("type")))
                for (StrictJson.Obj content : message.objects("content")) {
                    require(!"refusal".equals(content.string("type")), "market_summary_provider_refusal");
                    if ("output_text".equals(content.string("type"))) texts.add(content.string("text"));
                }
            require(texts.size() == 1, "market_summary_one_output_required"); StrictJson.Obj actual = StrictJson.parseObject(texts.getFirst());
            if ("generationRequestDigest".equals(field)) {
                ArrayNode projected = StrictJson.newArray(); for (StrictJson.Obj claim : summary.objects("claims")) {
                    ObjectNode value = (ObjectNode) claim.node().deepCopy(); value.remove("claimId"); projected.add(value);
                }
                require(actual.array("claims").equals(projected), "market_summary_generated_content_binding");
            } else {
                require(data.object("draft").array("claims").equals(summary.array("claims")), "market_summary_verified_draft_binding");
                Set<String> checked = new HashSet<>(); for (StrictJson.Obj check : summary.object("verification").objects("checks")) {
                    String target = check.string("targetId"); checked.add(target);
                    require(check.node().equals(actual.object("checks").raw(target)), "market_summary_verifier_binding");
                }
                actual.object("checks").exactly(checked);
            }
        }
        require(!summary.string("generationRequestDigest").equals(summary.string("verificationRequestDigest")), "market_summary_request_identity");
    }

    private static byte[] marketArtifact(Path output, String kind, String sha, JsonNode expected) {
        require(sha.matches("[0-9a-f]{64}"), "market_artifact_digest"); byte[] bytes = read(output.resolve("market").resolve(kind).resolve(sha + ".json"));
        require(Canonical.sha256(bytes).equals(sha) && StrictJson.parseObject(bytes).node().equals(expected), "market_artifact_hash_or_content"); return bytes;
    }

    private static byte[] marketRaw(Path output, String sha) {
        require(sha.matches("[0-9a-f]{64}"), "market_raw_digest"); byte[] bytes = read(output.resolve("market/raw").resolve(sha + ".bin"));
        require(Canonical.sha256(bytes).equals(sha), "market_raw_hash"); return bytes;
    }

    private void registerMarketBlobs(String namespace, StrictJson.Obj record, Map<String, Blob> blobs) {
        Path output = settings.bundle().getParent();
        blobs.put(namespace + "-snapshot", blob("briefing_input", marketArtifact(output, "snapshots", record.string("marketSnapshotSha256"), record.object("marketSnapshot").node())));
        blobs.put(namespace + "-context", blob("briefing_input", StrictJson.write(record.object("context").node())));
        if (record.has("marketContext")) {
            blobs.put(namespace + "-market-context", blob("briefing_input",
                    marketArtifact(output, "contexts", record.object("context").string("marketContextSha256"), record.object("marketContext").node())));
            StrictJson.Obj result = record.object("summaryResult");
            String sha = result.string("frozenInputSha256");
            byte[] bytes = read(output.resolve("market/frozen-inputs/" + sha + ".json"));
            require(Canonical.sha256(bytes).equals(sha), "market_context_frozen_input_hash");
            blobs.put(namespace + "-frozen-input", blob("briefing_input", bytes));
        }
        if (!record.isNull("summaryResult")) blobs.put(namespace + "-summary", blob("analysis_result",
                marketArtifact(output, "summaries", record.string("summaryResultSha256"), record.object("summaryResult").node())));
        for (StrictJson.Obj ref : record.object("marketSnapshot").objects("rawRefs")) blobs.put(namespace + "-raw-" + ref.string("sha256"),
                new Blob("raw_document", marketRaw(output, ref.string("sha256")), "application/octet-stream"));
    }

    static void applyMarketEnrichment(ObjectNode payload, ObjectNode snapshot, StrictJson.Obj record) {
        payload.set("marketVariables", record.object("marketSnapshot").object("marketVariables").node().deepCopy());
        ObjectNode lineage = snapshot.putObject("marketEnrichment").put("contextSha256", record.string("contextSha256"))
                .put("marketSnapshotSha256", record.string("marketSnapshotSha256"));
        lineage.set("context", record.object("context").node().deepCopy());
        if (record.has("frozenExecution")) lineage.set("frozenExecution", record.object("frozenExecution").node().deepCopy());
        if (record.has("marketContext")) {
            lineage.set("marketContext", record.object("marketContext").node().deepCopy());
            lineage.set("forecasts", record.object("summaryResult").array("forecasts").deepCopy());
            lineage.set("forecastEvaluations", record.object("summaryResult").array("forecastEvaluations").deepCopy());
        }
        ArrayNode failures = (ArrayNode) payload.path("metadata").path("failures");
        for (int index = failures.size() - 1; index >= 0; index--) if ("marketVariables".equals(failures.get(index).path("section").stringValue())) failures.remove(index);
        failure(failures, "marketVariables", "RETROSPECTIVE_DAILY_SNAPSHOT", "회차 마감 이전 일별 지표를 나중에 조회한 과거 시뮬레이션입니다. 당시 장중 관측값·개별 뉴스의 주가 영향 인과관계를 입증하지 않습니다.");
        if (record.isNull("summaryResult") || !"PASS".equals(record.object("summaryResult").object("verification").string("status"))) {
            snapshot.putObject("marketSummary").put("status", "unavailable").put("reason", "시장 요약의 생성·근거 검증을 통과하지 않아 공개하지 않습니다."); return;
        }
        StrictJson.Obj summary = record.object("summaryResult");
        ObjectNode saved = snapshot.putObject("marketSummary").put("text", summary.string("text")).put("generatedAt", summary.string("generatedAt"))
                .put("resultVersion", summary.string("resultVersion"));
        ArrayNode evidence = saved.putArray("evidenceIds"); Set<String> ids = new LinkedHashSet<>();
        for (StrictJson.Obj claim : summary.objects("claims")) ids.addAll(claim.strings("evidenceIds")); ids.forEach(evidence::add);
        lineage.put("summaryResultSha256", record.string("summaryResultSha256")).put("scopeNote", summary.string("scopeNote"));
    }

    record MarketPublicationTimes(Instant generatedAt, Instant publishedAt, Instant artifactCreatedAt) { }

    /** Saved producer times determine the new enrichment publication; re-import never advances a clock. */
    static MarketPublicationTimes marketPublicationTimes(Instant newsGeneratedAt, StrictJson.Obj record) {
        Instant generated = newsGeneratedAt;
        if (!record.isNull("summaryResult")) {
            Instant summaryGenerated = Instant.parse(record.object("summaryResult").string("generatedAt"));
            if (summaryGenerated.isAfter(generated)) generated = summaryGenerated;
        }
        Instant published = Instant.parse(record.object("marketSnapshot").string("fetchedAt"));
        if (generated.isAfter(published)) published = generated;
        for (StrictJson.Obj receipt : record.objects("receipts")) if (receipt.has("finishedAt") && !receipt.isNull("finishedAt")) {
            Instant finished = Instant.parse(receipt.string("finishedAt"));
            if (finished.isAfter(published)) published = finished;
        }
        return new MarketPublicationTimes(generated, published, published);
    }

    private static void validateSimulationIdentity(StrictJson.Obj bundle, StrictJson.Obj round) {
        StrictJson.Obj identity = round.object("identity");
        require(Canonical.digest(identity.node()).equals(round.string("identitySha256")), "simulation_identity_hash");
        for (String name : List.of("mode", "runId", "sourceFileSha256", "clockFileSha256")) require(bundle.string(name).equals(identity.string(name)), "simulation_identity_context");
        require(identity.string("date").equals(round.string("date")) && identity.string("edition").equals(round.string("edition"))
                && identity.object("window").node().equals(round.object("window").node())
                && identity.object("authorization").node().equals(bundle.object("authorization").node())
                && identity.object("previous").node().equals(round.object("previous").node())
                && !identity.bool("operationalCollectionGate") && "round-simulation-v1".equals(identity.string("contextVersion"))
                && Canonical.digest(round.array("inputSources")).equals(identity.string("candidateInputSha256")), "simulation_frozen_context");
        require(Instant.parse(identity.object("baseline").string("from")).equals(LocalDate.of(2026, 10, 1).atTime(17, 30).atZone(KST).toInstant())
                && "simulation_baseline_not_service_first_round".equals(identity.object("baseline").string("meaning")), "simulation_baseline");
        List<String> names = new ArrayList<>(List.of("importance.md", "selection.md", "generation-morning.md", "generation-evening.md", "verification.md",
                "importance.schema.json", "selection.schema.json", "generation.schema.json", "verification.schema.json"));
        if (simulationQualityV2(identity)) names.addAll(List.of("selection-v2.md", "selection-v2.schema.json",
                "generation-v2-morning.md", "generation-v2-evening.md", "novelty.md", "novelty.schema.json", "novelty-verification.md"));
        boolean grouped = BriefingGroupedSimulationRules.SCHEMA.equals(bundle.string("schemaVersion"));
        if (grouped) names.addAll(List.of("grouped-selection.md", "grouped-selection.schema.json",
                "grouped-generation-morning.md", "grouped-generation-evening.md", "grouped-verification.md"));
        StrictJson.Obj prompts = identity.object("promptArtifacts"); prompts.exactly(Set.copyOf(names));
        for (String name : names) {
            String resource = name.startsWith("grouped-") ? "/briefing/prompts/grouped-issues/" + name.substring("grouped-".length())
                    : "/briefing/prompts/round-simulation/" + name;
            try (var stream = BriefingReplayImporter.class.getResourceAsStream(resource)) {
                require(stream != null && Canonical.sha256(stream.readAllBytes()).equals(prompts.string(name)), "simulation_prompt_hash");
            } catch (IOException unavailable) { throw new IllegalArgumentException("Simulation prompt is unavailable", unavailable); }
        }
    }

    static boolean simulationQualityV2(StrictJson.Obj identity) {
        if (!identity.has("qualityPolicy")) {
            require(!identity.has("noveltyHistorySha256"), "simulation_legacy_novelty_identity");
            return false;
        }
        require("novelty-recovery-v2".equals(identity.string("qualityPolicy")), "simulation_quality_policy");
        require(identity.string("noveltyHistorySha256").matches("[0-9a-f]{64}"), "simulation_novelty_history_digest");
        return true;
    }

    /** The history is reconstructed only from previously validated SELECTED/PASS results in chronological order. */
    static void appendSimulationNoveltyHistory(ArrayNode history, StrictJson.Obj round) {
        require("SELECTED".equals(round.string("selectionStatus"))
                && "PASS".equals(round.object("result").object("verification").string("status")), "simulation_novelty_history_not_published");
        for (StrictJson.Obj selected : round.objects("selected")) {
            StrictJson.Obj generated = round.object("result").objects("items").stream()
                    .filter(item -> item.string("issueId").equals(selected.string("issueId"))).findFirst().orElseThrow();
            ObjectNode item = history.addObject().put("roundId", round.string("roundId")).put("issueId", selected.string("issueId"))
                    .put("eventKey", selected.has("eventKey") ? selected.string("eventKey") : "").put("title", generated.string("title"));
            item.set("companyNames", selected.array("companyNames").deepCopy());
            item.set("claims", generated.array("claims").deepCopy());
            ArrayNode sources = item.putArray("sources");
            for (StrictJson.Obj source : selected.objects("sources")) {
                ObjectNode projected = sources.addObject();
                for (String field : List.of("documentId", "bodySha256", "quote", "evidenceId", "url"))
                    if (source.has(field)) projected.set(field, source.raw(field).deepCopy());
            }
        }
    }

    static void validateSimulationNovelty(StrictJson.Obj round, ArrayNode history, Map<String, JsonNode> receipts) {
        StrictJson.Obj identity = round.object("identity");
        String historySha = Canonical.digest(history);
        require(historySha.equals(identity.string("noveltyHistorySha256")), "simulation_novelty_history_hash");
        if (!round.has("noveltyAudit")) {
            require(round.objects("selected").isEmpty(), "simulation_selected_novelty_audit_required");
            require(receipts.values().stream().noneMatch(value -> NOVELTY_STAGES.contains(StrictJson.Obj.of(value).string("stage"))),
                    "simulation_novelty_receipt_without_audit");
            return;
        }
        StrictJson.Obj audit = round.object("noveltyAudit");
        require("pass_history_event_novelty_v2".equals(audit.string("policy"))
                && round.string("identitySha256").equals(audit.string("contextSha256"))
                && historySha.equals(audit.string("historySha256"))
                && audit.string("candidateInputSha256").matches("[0-9a-f]{64}"), "simulation_novelty_audit_binding");
        List<String> historyIds = new ArrayList<>(); Map<String, StrictJson.Obj> old = new LinkedHashMap<>();
        for (JsonNode node : history) {
            StrictJson.Obj item = StrictJson.Obj.of(node); String id = item.string("issueId");
            require(old.putIfAbsent(id, item) == null, "simulation_novelty_duplicate_history_issue"); historyIds.add(id);
        }
        require(historyIds.equals(audit.strings("historyIssueIds")), "simulation_novelty_history_ids");
        Map<String, String> inputHashes = new LinkedHashMap<>();
        for (StrictJson.Obj source : round.objects("inputSources")) inputHashes.put(source.string("documentId"), source.string("bodySha256"));
        Set<String> seen = new HashSet<>(); List<String> kept = new ArrayList<>(), excluded = new ArrayList<>();
        Map<String, JsonNode> modelDecisions = new LinkedHashMap<>();
        for (StrictJson.Obj decision : audit.objects("decisions")) {
            decision.exactly(Set.of("documentId", "decision", "matchedIssueId", "reason", "delta", "quoteIds", "method"));
            String document = text(decision, "documentId"), status = decision.string("decision"), method = decision.string("method");
            String match = decision.stringOrNull("matchedIssueId"); List<String> quotes = decision.strings("quoteIds");
            require(inputHashes.containsKey(document) && seen.add(document)
                    && Set.of("NEW_EVENT", "MATERIAL_UPDATE", "REPEAT", "UNCERTAIN").contains(status)
                    && (match == null || old.containsKey(match)) && !decision.string("reason").isBlank()
                    && decision.string("reason").length() <= 500 && decision.string("delta").length() <= 700
                    && quotes.size() <= 8 && new HashSet<>(quotes).size() == quotes.size(), "simulation_novelty_decision");
            if ("no_history_no_model".equals(method)) require(history.isEmpty() && "NEW_EVENT".equals(status)
                    && match == null && quotes.isEmpty(), "simulation_novelty_no_history_decision");
            else if ("deterministic_body_digest".equals(method)) require("REPEAT".equals(status) && match != null
                    && quotes.isEmpty() && old.get(match).objects("sources").stream()
                    .anyMatch(source -> inputHashes.get(document).equals(source.string("bodySha256"))), "simulation_novelty_digest_repeat");
            else {
                require("model_evidence_comparison".equals(method) && !history.isEmpty(), "simulation_novelty_method");
                if ("NEW_EVENT".equals(status)) require(match == null && !quotes.isEmpty(), "simulation_novelty_new_evidence");
                if ("MATERIAL_UPDATE".equals(status)) require(match != null && !quotes.isEmpty()
                        && !decision.string("delta").isBlank(), "simulation_novelty_material_delta");
                if ("REPEAT".equals(status)) require(match != null, "simulation_novelty_repeat_match");
                ObjectNode raw = (ObjectNode) decision.node().deepCopy(); raw.remove("method"); modelDecisions.put(document, raw);
            }
            if (Set.of("NEW_EVENT", "MATERIAL_UPDATE").contains(status)) {
                require(old.values().stream().flatMap(item -> item.objects("sources").stream())
                        .noneMatch(source -> inputHashes.get(document).equals(source.string("bodySha256"))), "simulation_novelty_kept_exact_repeat");
                kept.add(document);
            } else excluded.add(document);
        }
        require(seen.size() <= 30 && kept.equals(audit.strings("keptDocumentIds"))
                && excluded.equals(audit.strings("excludedDocumentIds")), "simulation_novelty_partition");
        if (audit.bool("modelCalled")) {
            require(audit.bool("verificationCalled"), "simulation_novelty_verification_required");
            StrictJson.Obj initial = audit.object("rawModelResponse").exactly(Set.of("decisions"));
            initial.object("decisions").exactly(modelDecisions.keySet());
            StrictJson.Obj verified = audit.object("rawVerificationResponse").exactly(Set.of("decisions"));
            StrictJson.Obj decisions = verified.object("decisions").exactly(modelDecisions.keySet());
            require(!modelDecisions.isEmpty(), "simulation_novelty_model_empty");
            modelDecisions.forEach((document, value) -> require(value.equals(decisions.raw(document)), "simulation_novelty_verified_decision_binding"));
            for (String stage : NOVELTY_STAGES) require(receipts.values().stream().map(StrictJson.Obj::of)
                    .anyMatch(receipt -> stage.equals(receipt.string("stage")) && success(receipt)
                            && receipt.bool("usageKnown") && receipt.count("httpStatus") == 200), "simulation_novelty_receipt_required");
        } else require(modelDecisions.isEmpty() && audit.isNull("rawModelResponse") && !audit.bool("verificationCalled")
                && audit.isNull("rawVerificationResponse") && receipts.values().stream()
                .noneMatch(value -> NOVELTY_STAGES.contains(StrictJson.Obj.of(value).string("stage"))), "simulation_novelty_unexpected_model");
        for (StrictJson.Obj selected : round.objects("selected")) for (StrictJson.Obj source : selected.objects("sources"))
            require(kept.contains(source.string("documentId")), "simulation_novelty_selected_rejected_document");
    }

    /** An audit cannot substitute a different model answer or an unbound candidate body for the paid recording. */
    private void validateSimulationNoveltyRecording(StrictJson.Obj round, Map<String, JsonNode> receipts, Map<String, Source> inputs) {
        StrictJson.Obj audit = round.object("noveltyAudit"); Set<String> bound = new HashSet<>();
        Path calls = settings.bundle().getParent().resolve("calls");
        for (JsonNode node : receipts.values()) {
            StrictJson.Obj receipt = StrictJson.Obj.of(node);
            String stage = receipt.string("stage");
            if (!NOVELTY_STAGES.contains(stage)) continue;
            boolean verification = "round_simulation_novelty_verification".equals(stage);
            String responseField = verification ? "rawVerificationResponse" : "rawModelResponse";
            String key = receipt.string("requestDigest");
            byte[] requestBytes = read(calls.resolve(key + ".request.json"));
            require(key.equals(Canonical.sha256(requestBytes)), "simulation_novelty_request_recording_hash");
            StrictJson.Obj request = StrictJson.parseObject(requestBytes), data = StrictJson.parseObject(request.string("input"));
            require(stage.equals(request.object("text").object("format").string("name"))
                    && receipt.string("model").equals(request.string("model"))
                    && round.string("identitySha256").equals(data.string("contextSha256"))
                    && round.string("identitySha256").equals(Canonical.digest(data.object("context").node()))
                    && audit.string("historySha256").equals(data.string("noveltyHistorySha256"))
                    && audit.string("historySha256").equals(Canonical.digest(data.array("noveltyHistory")))
                    && audit.string("policy").equals(data.string("noveltyPolicy"))
                    && audit.string("candidateInputSha256").equals(data.string("noveltyCandidateInputSha256")), "simulation_novelty_request_binding");
            if (verification) require(data.object("priorNoveltyDecisions").node().equals(audit.object("rawModelResponse").node()),
                    "simulation_novelty_verification_prior_binding");
            Set<String> recordedDocuments = new HashSet<>();
            for (StrictJson.Obj document : data.objects("documents")) {
                String documentId = document.string("documentId"), bodySha = document.string("bodySha256"), body = document.string("body");
                Source source = inputs.get(documentId + "\u0000" + bodySha);
                require(recordedDocuments.add(documentId) && source != null && source.body().equals(body)
                        && Canonical.sha256(body).equals(bodySha), "simulation_novelty_recorded_body_binding");
                Set<String> quoteIds = new HashSet<>();
                for (StrictJson.Obj quote : document.objects("quoteCatalog")) {
                    int start = quote.count("start"), end = quote.count("end");
                    require(quoteIds.add(text(quote, "quoteId")) && documentId.equals(quote.string("documentId"))
                            && start < end && end <= body.codePointCount(0, body.length())
                            && quote.string("text").equals(body.substring(body.offsetByCodePoints(0, start), body.offsetByCodePoints(0, end))),
                            "simulation_novelty_recorded_quote_binding");
                }
                StrictJson.Obj decision = audit.object(responseField).object("decisions").object(documentId);
                require(quoteIds.containsAll(decision.strings("quoteIds")), "simulation_novelty_decision_quote_membership");
            }
            require(recordedDocuments.equals(Set.copyOf(audit.object(responseField).object("decisions").node().propertyNames())),
                    "simulation_novelty_recorded_document_coverage");
            if (!success(receipt) || !receipt.bool("usageKnown") || receipt.count("httpStatus") != 200) continue;
            byte[] responseBytes = read(calls.resolve(key + ".response.json"));
            require(Canonical.sha256(responseBytes).equals(receipt.string("responseSha256")), "simulation_novelty_response_recording_hash");
            StrictJson.Obj response = StrictJson.parseObject(responseBytes); List<String> texts = new ArrayList<>();
            require(receipt.string("status").equals(response.string("status")) && receipt.string("responseId").equals(response.string("id"))
                    && receipt.count("inputTokens") == response.object("usage").count("input_tokens")
                    && receipt.count("outputTokens") == response.object("usage").count("output_tokens"), "simulation_novelty_recorded_receipt_binding");
            for (StrictJson.Obj output : response.objects("output")) {
                if (!"message".equals(output.string("type"))) continue;
                for (StrictJson.Obj content : output.objects("content")) {
                    require(!"refusal".equals(content.string("type")), "simulation_novelty_provider_refusal");
                    if ("output_text".equals(content.string("type"))) texts.add(content.string("text"));
                }
            }
            require(texts.size() == 1 && StrictJson.parseObject(texts.getFirst()).node().equals(audit.object(responseField).node()),
                    "simulation_novelty_recorded_response_binding");
            bound.add(stage);
        }
        require(bound.equals(NOVELTY_STAGES), "simulation_novelty_model_recording_required");
    }

    private static Map<String, Source> simulationInputs(StrictJson.Obj round, Map<String, Source> pool,
            PublicationClockRegistry clocks, List<PublicationClockRegistry.Clock> windowClocks) {
        Map<String, Source> inputs = new LinkedHashMap<>(); Set<String> hashes = new HashSet<>();
        Set<String> inWindow = new HashSet<>(); windowClocks.forEach(clock -> inWindow.add(clock.key()));
        for (StrictJson.Obj input : round.objects("inputSources")) {
            String key = input.string("documentId") + "\u0000" + input.string("bodySha256"); Source source = pool.get(key);
            require(source != null && source.version().equals(input.string("documentVersion")) && inWindow.contains(key)
                    && inputs.putIfAbsent(key, source) == null && hashes.add(source.bodySha()), "simulation_input_window_or_duplicate");
        }
        Set<String> expectedHashes = new HashSet<>(); windowClocks.forEach(clock -> expectedHashes.add(clock.bodySha256()));
        require(hashes.equals(expectedHashes), "simulation_input_coverage");
        Set<String> refs = new HashSet<>();
        for (StrictJson.Obj ref : round.objects("clockRefs")) {
            String key = ref.string("documentId") + "\u0000" + ref.string("bodySha256"); PublicationClockRegistry.Clock clock = clocks.verified.get(key);
            require(clock != null && inputs.containsKey(key) && refs.add(key)
                    && clock.publishedAt().equals(Instant.parse(ref.string("publishedAt")))
                    && clock.recordSha256().equals(ref.string("clockRecordSha256")) && clock.htmlSha256().equals(ref.string("htmlSha256")), "simulation_clock_reference");
        }
        require(refs.equals(inputs.keySet()), "simulation_input_clock_set"); return inputs;
    }

    private static Map<String, JsonNode> simulationReceiptLedger(List<StrictJson.Obj> receipts) {
        Map<String, JsonNode> result = new LinkedHashMap<>();
        for (StrictJson.Obj receipt : receipts) {
            String digest = text(receipt, "requestDigest"); require(digest.matches("[0-9a-f]{64}"), "simulation_receipt_digest");
            text(receipt, "stage"); text(receipt, "model"); text(receipt, "status");
            Long in = token(receipt.raw("inputTokens")), out = token(receipt.raw("outputTokens"));
            require(!receipt.bool("usageKnown") || (in != null && out != null), "simulation_receipt_usage");
            require(result.putIfAbsent(digest, receipt.node()) == null, "simulation_duplicate_paid_receipt");
        }
        return result;
    }

    /** Preserve observed provider bytes even for held drafts; absent unknown-transport bodies are never invented. */
    private void paidResponseBlobs(String namespace, Map<String, JsonNode> receipts, Map<String, Blob> blobs) {
        for (var entry : receipts.entrySet()) {
            StrictJson.Obj receipt = StrictJson.Obj.of(entry.getValue());
            if (!receipt.has("responseSha256") || receipt.isNull("responseSha256")) continue;
            String responseSha = receipt.string("responseSha256"), digest = entry.getKey();
            require(responseSha.matches("[0-9a-f]{64}"), "simulation_provider_response_digest");
            Path calls = settings.bundle().getParent().resolve("calls");
            Path requestFile = calls.resolve(digest + ".request.json"), responseFile = calls.resolve(digest + ".response.json");
            try {
                require(calls.equals(calls.toRealPath()) && Files.isRegularFile(requestFile, LinkOption.NOFOLLOW_LINKS)
                        && Files.isRegularFile(responseFile, LinkOption.NOFOLLOW_LINKS), "simulation_provider_recording_missing");
            } catch (IOException unavailable) { throw new IllegalArgumentException("Simulation provider recording is unavailable", unavailable); }
            byte[] request = read(requestFile), response = read(responseFile);
            require(request.length <= ArtifactFileStore.MAX_READ_BYTES && response.length <= ArtifactFileStore.MAX_READ_BYTES
                    && digest.equals(Canonical.sha256(request)) && responseSha.equals(Canonical.sha256(response)), "simulation_provider_recording_hash");
            rejectCredentialFields(StrictJson.parseObject(request).node()); // Provider credentials never belong in a request recording.
            blobs.put(namespace + "-request-" + digest, blob("ai_submit", request));
            String kind = receipt.string("stage").endsWith("_verification") ? "verification_receipt" : "analysis_result";
            blobs.put(namespace + "-response-" + digest, new Blob(kind, response, "application/octet-stream"));
        }
    }

    private static void validateSimulationSuccessReceipts(String edition, StrictJson.Obj result, Map<String, JsonNode> receipts, boolean qualityV2) {
        Set<String> stages = new HashSet<>();
        String generation = "round_simulation_" + edition + "_generation", verification = "round_simulation_" + edition + "_verification";
        Set<String> expected = Set.of("round_simulation_importance", "round_simulation_selection", generation, verification);
        for (JsonNode value : receipts.values()) {
            StrictJson.Obj receipt = StrictJson.Obj.of(value);
            require(expected.contains(receipt.string("stage")) || (qualityV2 && NOVELTY_STAGES.contains(receipt.string("stage"))), "simulation_receipt_phase_scope");
            // Earlier failed/incomplete/unknown paid attempts remain accounting, never a successful result.
            if (success(receipt) && receipt.bool("usageKnown") && receipt.has("httpStatus")
                    && !receipt.isNull("httpStatus") && receipt.count("httpStatus") == 200) {
                text(receipt, "responseId"); if (expected.contains(receipt.string("stage"))) stages.add(receipt.string("stage"));
            }
        }
        require(stages.equals(expected), "simulation_phase_coverage");
        Set<String> used = new HashSet<>();
        String generationDigest = text(result, "generationRequestDigest"), verificationDigest = text(result, "verificationRequestDigest");
        require(!generationDigest.equals(verificationDigest), "simulation_final_request_identity");
        Set<String> finalDigests = new HashSet<>();
        List<StrictJson.Obj> finalUsage = result.objects("usage");
        require(finalUsage.size() == 2, "simulation_final_usage_pair");
        for (StrictJson.Obj receipt : finalUsage) {
            require(receipt.node().equals(receipts.get(receipt.string("requestDigest"))) && success(receipt)
                    && receipt.bool("usageKnown") && receipt.count("httpStatus") == 200, "simulation_result_usage_binding");
            String digest = receipt.string("requestDigest"), stage = receipt.string("stage");
            require(finalDigests.add(digest) && ((generation.equals(stage) && generationDigest.equals(digest))
                    || (verification.equals(stage) && verificationDigest.equals(digest))), "simulation_final_request_binding");
            used.add(receipt.string("stage"));
        }
        require(used.equals(Set.of(generation, verification)), "simulation_result_phase_coverage");
    }

    private Map<String, Source> sources(byte[] bytes) {
        Map<String, Source> result = new LinkedHashMap<>();
        String text;
        try {
            text = StandardCharsets.UTF_8.newDecoder().onMalformedInput(java.nio.charset.CodingErrorAction.REPORT)
                    .onUnmappableCharacter(java.nio.charset.CodingErrorAction.REPORT).decode(java.nio.ByteBuffer.wrap(bytes)).toString();
        } catch (java.nio.charset.CharacterCodingException invalid) { throw new IllegalArgumentException("Briefing replay rejected: source_utf8"); }
        for (String line : text.split("\\r?\\n", -1)) {
            if (line.isBlank()) continue;
            StrictJson.Obj row = StrictJson.parseObject(line);
            String id = text(row, "documentId"), body = text(row, "body"), hash = text(row, "bodySha256");
            require(hash.matches("[0-9a-f]{64}") && hash.equals(Canonical.sha256(body)), "source_body_digest");
            String provider = optional(row, "sourceId", optional(row, "bodyProvider", optional(row, "provider", "replay-source")));
            String collected = optional(row, "collectedAt", optional(row, "bodyAcquiredAt", null));
            require(collected != null, "source_collected_at");
            Source source = new Source(id, "sha256-" + hash, hash, body, text(row, "url"), text(row, "title"),
                    provider, text(row, "sourceKind"), Instant.parse(collected), row, line.getBytes(StandardCharsets.UTF_8));
            require(Set.of("news", "disclosure").contains(source.kind()), "source_kind");
            Source previous = result.putIfAbsent(source.key(), source);
            require(previous == null || Arrays.equals(previous.raw(), source.raw()), "ambiguous_source_version");
        }
        require(!result.isEmpty(), "empty_source_pool"); return result;
    }

    private Map<String, Issue> selections(StrictJson.Obj bundle, Map<String, Source> pool) {
        return selections(bundle, pool, false);
    }

    private Map<String, Issue> selections(StrictJson.Obj bundle, Map<String, Source> pool, boolean allowEmpty) {
        Map<String, Issue> result = new LinkedHashMap<>();
        List<StrictJson.Obj> selected = bundle.objects("selected");
        require((allowEmpty || !selected.isEmpty()) && selected.size() <= 3, "selection_limit");
        for (StrictJson.Obj item : selected) {
            String id = text(item, "issueId"); int rank = item.count("rank");
            require(rank == result.size() + 1, "selection_rank");
            text(item, "reason");
            List<Company> companies = new ArrayList<>();
            for (String name : item.strings("companyNames")) {
                List<Company> matches = jdbc.query("""
                        SELECT id,name FROM companies WHERE lower(name)=lower(?)
                            OR EXISTS(SELECT 1 FROM unnest(aliases) alias WHERE lower(alias)=lower(?))
                        """, (rs, n) -> new Company(rs.getString("id"), rs.getString("name")), name, name);
                require(matches.size() == 1, "company_catalog_match");
                if (companies.stream().noneMatch(company -> company.id().equals(matches.get(0).id()))) companies.add(matches.get(0));
            }
            // Simulation may contain a market-wide issue without a proven link to a catalogued company.
            // Supplied names still require an exact existing catalog match; never invent a company to fill the array.
            require(allowEmpty || !companies.isEmpty(), "company_required");
            List<Citation> citations = new ArrayList<>();
            for (StrictJson.Obj ref : item.objects("sources")) {
                String document = text(ref, "documentId"), bodyHash = text(ref, "bodySha256");
                Source source = pool.get(document + "\u0000" + bodyHash);
                require(source != null && source.version().equals(ref.string("documentVersion"))
                        && source.url().equals(ref.string("url")), "selected_source_identity");
                int start = ref.count("start"), end = ref.count("end"); String quote = text(ref, "quote");
                int length = source.body().codePointCount(0, source.body().length());
                require(end > start && end <= length, "quote_offsets");
                String exact = source.body().substring(source.body().offsetByCodePoints(0, start), source.body().offsetByCodePoints(0, end));
                require(exact.equals(quote), "quote_not_exact");
                citations.add(new Citation(text(ref, "evidenceId"), source, quote, start, end));
            }
            require(!citations.isEmpty(), "selection_evidence");
            require(result.putIfAbsent(id, new Issue(id, rank, item.string("reason"), companies, citations)) == null, "duplicate_issue");
        }
        return result;
    }

    private static void validateGeneration(StrictJson.Obj edition, Map<String, Issue> selected) {
        Instant.parse(edition.string("generatedAt"));
        List<StrictJson.Obj> items = edition.objects("items"); require(items.size() == selected.size(), "generated_item_count");
        Set<String> expectedChecks = new HashSet<>(); Set<String> issueIds = new HashSet<>();
        for (int position = 0; position < items.size(); position++) {
            StrictJson.Obj item = items.get(position); String id = text(item, "issueId"); Issue issue = selected.get(id);
            require(issue != null && issueIds.add(id) && item.count("rank") == position + 1 && issue.rank() == position + 1, "generated_issue_rank");
            text(item, "title"); expectedChecks.add(id + ":title");
            Set<String> allowed = new HashSet<>(issue.citations().stream().map(Citation::id).toList());
            if (item.has("titleEvidenceIds")) cited(item.strings("titleEvidenceIds"), allowed);
            List<StrictJson.Obj> claims = item.objects("claims"); require(!claims.isEmpty(), "empty_claims");
            for (int i = 0; i < claims.size(); i++) {
                StrictJson.Obj claim = claims.get(i); text(claim, "text");
                require(Set.of("fact", "plan", "outlook").contains(claim.string("type")), "claim_type");
                cited(claim.strings("evidenceIds"), allowed); expectedChecks.add(id + ":claim:" + i);
            }
        }
        StrictJson.Obj verification = edition.object("verification");
        require("PASS".equals(verification.string("status")), "verification_not_pass");
        Set<String> actual = new HashSet<>();
        for (StrictJson.Obj check : verification.objects("checks")) {
            require(actual.add(text(check, "targetId")) && "SUPPORTED".equals(check.string("verdict"))
                    && check.bool("typeAppropriate") && check.bool("temporalAppropriate")
                    && check.bool("noUnsupportedNumbers") && check.bool("noInvestmentAdvice"), "verification_check_failed");
            text(check, "reason");
        }
        require(actual.equals(expectedChecks), "verification_target_coverage");
    }

    private static void validateReceipts(StrictJson.Obj bundle, Map<String, StrictJson.Obj> editions) {
        Map<String, JsonNode> receipts = new LinkedHashMap<>();
        Map<String, StrictJson.Obj> byRequest = new LinkedHashMap<>();
        Set<String> stages = new HashSet<>();
        for (StrictJson.Obj receipt : bundle.objects("receipts")) {
            String stage = text(receipt, "stage"); text(receipt, "model"); String response = text(receipt, "responseId");
            String request = text(receipt, "requestDigest"); require(request.matches("[0-9a-f]{64}"), "request_digest");
            String status = receipt.string("status");
            require(success(receipt) || "incomplete".equals(status), "receipt_status");
            if (success(receipt)) stages.add(stage);
            if (receipt.has("httpStatus")) require(receipt.count("httpStatus") == 200, "receipt_http_status");
            Long input = token(receipt.raw("inputTokens")), output = token(receipt.raw("outputTokens"));
            require(!receipt.bool("usageKnown") || (input != null && output != null), "unknown_usage");
            require(receipts.putIfAbsent(response, receipt.node()) == null, "duplicate_receipt");
            require(byRequest.putIfAbsent(request, receipt) == null, "duplicate_request_receipt");
        }
        validateCorrections(bundle, byRequest);
        require(stages.containsAll(Set.of("briefing_population_importance", "briefing_global_selection",
                "briefing_morning_generation", "briefing_morning_verification", "briefing_evening_generation",
                "briefing_evening_verification")), "receipt_stage_coverage");
        for (var entry : editions.entrySet()) {
            StrictJson.Obj edition = entry.getValue();
            List<StrictJson.Obj> usage = edition.objects("usage"); require(!usage.isEmpty(), "edition_usage_required");
            Set<String> expected = Set.of("briefing_" + entry.getKey() + "_generation", "briefing_" + entry.getKey() + "_verification");
            Set<String> editionStages = new HashSet<>();
            for (StrictJson.Obj receipt : usage) {
                require(receipt.node().equals(receipts.get(receipt.string("responseId"))), "edition_receipt_mismatch");
                require(success(receipt), "edition_receipt_not_completed");
                editionStages.add(receipt.string("stage"));
            }
            require(editionStages.equals(expected), "edition_receipt_stage_coverage");
        }
    }

    /**
     * A paid, known truncated assessment stays in accounting as incomplete. Only a recorded operator-approved,
     * source-bound correction to a distinct completed assessment may supersede it; no failed/unknown or edition
     * generation/verifier call can be made acceptable by this audit. Completed coverage errors also retain their usage.
     */
    private static void validateCorrections(StrictJson.Obj bundle, Map<String, StrictJson.Obj> receipts) {
        Set<String> correctedOriginals = new HashSet<>();
        Set<String> replacements = new HashSet<>();
        if (bundle.has("coverageCorrections")) for (StrictJson.Obj correction : bundle.objects("coverageCorrections")) {
            require("zoop-assessment-coverage-correction-v2".equals(correction.string("schemaVersion")), "correction_schema");
            String originalDigest = text(correction, "originalRequestDigest");
            String correctedDigest = text(correction, "correctedRequestDigest");
            require(!originalDigest.equals(correctedDigest) && correctedOriginals.add(originalDigest)
                    && replacements.add(correctedDigest), "correction_identity");
            StrictJson.Obj original = receipts.get(originalDigest), replacement = receipts.get(correctedDigest);
            require(original != null && replacement != null, "correction_receipt_missing");
            require(correction.bool("operatorAuthorized")
                    && bundle.object("authorization").string("userInboxRef").equals(correction.string("operatorInboxRef"))
                    && bundle.string("sourceFileSha256").equals(correction.string("sourceSha256")), "correction_authorization");
            require("briefing_population_importance".equals(original.string("stage"))
                    && original.string("stage").equals(replacement.string("stage"))
                    && original.string("model").equals(replacement.string("model")), "correction_scope");
            require(original.count("httpStatus") == 200 && correction.count("originalHttpStatus") == 200
                    && original.bool("usageKnown") && correction.bool("originalUsageKnown")
                    && token(original.raw("inputTokens")) != null && token(original.raw("outputTokens")) != null
                    && original.string("status").equals(correction.string("originalStatus")), "correction_original_not_known");
            require(success(replacement) && replacement.count("httpStatus") == 200 && replacement.bool("usageKnown")
                    && token(replacement.raw("inputTokens")) != null && token(replacement.raw("outputTokens")) != null,
                    "correction_replacement_not_completed");
            String reason = correction.string("reason");
            String policy = correction.string("correctionPolicy"); int outputLimit = correction.count("maxOutputTokens");
            if ("operator_authorized_known_output_truncation".equals(reason)) {
                require("incomplete".equals(original.string("status"))
                        && "max_output_tokens".equals(correction.string("originalIncompleteReason"))
                        && "required-document-id-object-v2".equals(policy) && outputLimit == 12000, "correction_not_known_truncation");
            } else if ("completed_response_document_coverage_error".equals(reason)) {
                require("completed".equals(original.string("status")) && correction.isNull("originalIncompleteReason"),
                        "correction_not_completed_coverage_error");
                // Retain historical array corrections honestly; do not relabel their old 8k request as the new object policy.
                require(("required-document-id-object-v2".equals(policy) && outputLimit == 12000)
                        || ("input-id-array-v1".equals(policy) && outputLimit == 8000), "correction_completed_policy");
            } else require(false, "correction_reason");
        }
        for (var entry : receipts.entrySet()) {
            if ("incomplete".equals(entry.getValue().string("status"))) {
                require(correctedOriginals.contains(entry.getKey()), "incomplete_without_authorized_correction");
            }
        }
    }

    private static boolean success(StrictJson.Obj receipt) {
        return Set.of("completed", "succeeded").contains(receipt.string("status"));
    }

    private ObjectNode grants(String run, String sha, List<Source> sources) {
        ObjectNode root = StrictJson.newObject().put("schemaVersion", "zoop-ai-s1-1").put("scope", "development_replay")
                .put("runId", run).put("sourceFileSha256", sha).put("userInboxRef", settings.userInboxRef());
        ArrayNode values = root.putArray("grants");
        for (Source source : sources) {
            ObjectNode grant = values.addObject().put("grantId", grantId(run, source)).put("revision", sha)
                    .put("sourceId", source.provider()).put("enabled", true).put("rights", "known").putNull("expiresAt");
            grant.putArray("allowedOperations").add("read").add("store").add("model-send").add("quote-display");
            grant.putArray("recipients").add("openai");
            grant.putArray("purposes").add("briefing-outlook").add("semantic-verification");
            grant.putArray("evidence").add("development_replay_only:" + settings.userInboxRef()).add("sha256:" + sha);
        }
        return root;
    }

    private Round round(String namespace, String edition, LocalDate date, LocalDate start, String sourceSha, String bundleSha,
            String run, StrictJson.Obj historical, Map<String, Issue> selected, StrictJson.Obj generation,
            Map<String, Source> documents, Instant published) {
        Instant scheduled = date.atTime("morning".equals(edition) ? LocalTime.of(9, 20) : LocalTime.of(17, 30)).atZone(KST).toInstant();
        Instant generated = Instant.parse(generation.string("generatedAt"));
        String id = namespace + "-" + edition;
        ObjectNode payload = StrictJson.newObject().put("id", id).put("date", date.toString()).put("edition", edition)
                .put("scheduledAt", scheduled.toString()).put("generatedAt", generated.toString()).putNull("graphVersion")
                .put("reviewRevision", 0).putNull("ruleRevision").putNull("emptyReason").put("selectedFrom", selected.size())
                .putNull("marketVariables").putNull("outlook");
        payload.putObject("dataWindow").put("start", start.atStartOfDay(KST).toInstant().toString())
                .put("end", scheduled.toString()).put("openStart", false);
        ObjectNode references = payload.putObject("references"); ArrayNode eventIds = references.putArray("eventIds");
        Set<String> allEvidence = new LinkedHashSet<>(), allCompanies = new LinkedHashSet<>();
        ArrayNode items = payload.putArray("items");
        for (StrictJson.Obj output : generation.objects("items")) {
            Issue issue = selected.get(output.string("issueId")); eventIds.add(issue.id());
            Set<String> evidence = new LinkedHashSet<>(issue.citations().stream().map(Citation::id).toList()); allEvidence.addAll(evidence);
            ObjectNode item = items.addObject().put("eventId", issue.id()).put("rank", issue.rank()).put("title", output.string("title"))
                    .putNull("eventTime").put("timePrecision", "unknown").putNull("reportedAt").put("reason", issue.reason())
                    .put("evidenceCount", evidence.size());
            item.putArray("matchedCompanyIds"); item.putArray("documentSentiments"); ArrayNode itemEvidence = item.putArray("evidenceIds"); evidence.forEach(itemEvidence::add);
            ArrayNode companies = item.putArray("companies");
            for (Company company : issue.companies()) {
                allCompanies.add(company.id()); companies.addObject().put("id", company.id()).put("name", company.name())
                        .putNull("role").put("roleUnconfirmed", true).put("relationType", "INVOLVES");
            }
            ObjectNode support = item.putObject("sourceSupport").put("articleCount", issue.citations().stream().map(c -> c.source().id()).distinct().count())
                    .putNull("knownLineageCount").putNull("independentSourceCount");
            ArrayNode unknown = support.putArray("unknownLineageArticles"); issue.citations().stream().map(c -> c.source().id()).distinct().forEach(unknown::add);
            support.putArray("duplicateGroups");
            String summaryText = String.join("\n", output.objects("claims").stream()
                    .map(claim -> switch (claim.string("type")) { case "plan" -> "확인할 점: "; case "outlook" -> "조건부 전망: "; default -> ""; } + claim.string("text")).toList());
            ObjectNode summary = item.putObject("summary").put("text", summaryText).put("generatedAt", generated.toString())
                    .put("resultVersion", "sha256-" + Canonical.sha256(StrictJson.write(output.node())));
            ArrayNode cited = summary.putArray("evidenceIds");
            output.objects("claims").stream().flatMap(claim -> claim.strings("evidenceIds").stream()).distinct().forEach(cited::add);
        }
        ArrayNode evidenceIds = references.putArray("evidenceIds"); allEvidence.forEach(evidenceIds::add);
        ArrayNode companyIds = references.putArray("companyIds"); allCompanies.forEach(companyIds::add);
        ObjectNode metadata = payload.putObject("metadata").put("source", "zoop-briefing-development-replay")
                .put("asOf", scheduled.toString()).putNull("graphVersion").put("requestId", run).put("partial", true);
        metadata.putObject("schedule").put("morning", "09:20").put("evening", "17:30").put("confirmed", true);
        metadata.putObject("selection").put("basis", "market").put("reason", "사용자가 지정한 과거 주간 자료의 중요도를 AI가 평가한 개발 재생입니다.");
        ArrayNode failures = metadata.putArray("failures");
        failure(failures, "graphVersion", "DEVELOPMENT_REPLAY", "운영 권한·공개 그래프 승인 없이 localhost 개발 재생만 제공합니다.");
        failure(failures, "marketVariables", "SOURCE_UNAVAILABLE", "당시 KOSPI·KOSDAQ·환율을 수집하지 않아 시장 지표를 생성하지 않았습니다.");
        failure(failures, "sinceMorning", "DEVELOPMENT_REPLAY", "출근·퇴근 모두 같은 과거 주간 자료를 사용하므로 실제 아침 이후 변화나 장중 비교가 아닙니다.");
        failure(failures, "reportedAt", "DATE_UNCONFIRMED", "일부 뉴스 날짜는 공급자 추정이며 자료는 회차일 이후 실제 수집되었습니다. 원본 날짜 의미와 수집 시각은 보존했습니다.");
        ObjectNode snapshot = StrictJson.newObject(); snapshot.putObject("marketSummary").put("status", "unavailable").put("reason", "당시 시장 요약 생산자가 없어 저장된 요약이 없습니다.");
        ArrayNode bindings = snapshot.putArray("sourceBindings");
        for (Source source : documents.values()) {
            ObjectNode binding = bindings.addObject().put("documentId", source.id()).put("documentVersion", source.version())
                    .put("grantId", grantId(run, source)).put("grantRevision", sourceSha);
            binding.putArray("recipients").add("openai");
        }
        ObjectNode replay = snapshot.putObject("replay").put("scope", "development_replay").put("runId", run)
                .put("sourceFileSha256", sourceSha).put("bundleSha256", bundleSha).put("userInboxRef", settings.userInboxRef());
        replay.set("historicalReplay", historical.node().deepCopy());
        replay.put("inputArtifactId", namespace + "-input").put("resultArtifactId", namespace + "-" + edition + "-result")
                .put("verificationArtifactId", namespace + "-" + edition + "-verification");
        ObjectNode comparison = "morning".equals(edition) ? null : StrictJson.newObject().put("status", "unavailable")
                .put("reason", "동일 주간 자료의 형식 비교 재생으로 실제 아침 이후 추가 정보·장중 변화를 비교하지 않았습니다.");
        return new Round(id, date, edition, scheduled, start.atStartOfDay(KST).toInstant(), generated, published, payload, snapshot, comparison);
    }

    private void register(String id, Blob blob, ArtifactFileStore.StoredFile file, Instant at) {
        jdbc.update("""
                INSERT INTO artifacts(id,kind,storage_uri,sha256,bytes,media_type,created_at) VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(id) DO NOTHING
                """, id, blob.kind(), file.uri(), file.sha256(), file.bytes(), blob.mediaType(), Timestamp.from(at));
        Integer count = jdbc.queryForObject("SELECT count(*) FROM artifacts WHERE id=? AND kind=? AND storage_uri=? AND sha256=? AND bytes=? AND media_type=?",
                Integer.class, id, blob.kind(), file.uri(), file.sha256(), file.bytes(), blob.mediaType());
        require(Integer.valueOf(1).equals(count), "artifact_identity_conflict");
    }

    private void registerDocument(String namespace, Source source) {
        registerDocument(namespace, source, null);
    }

    private void registerDocument(String namespace, Source source, Instant publicationClock) {
        jdbc.update("""
                INSERT INTO articles(id,kind,provider,provider_key,lineage_key,current_version,access_status,created_at)
                VALUES(?,?,?,NULL,NULL,NULL,'available',?) ON CONFLICT(id) DO NOTHING
                """, source.id(), source.kind(), source.provider(), Timestamp.from(source.collected()));
        require(Integer.valueOf(1).equals(jdbc.queryForObject("SELECT count(*) FROM articles WHERE id=? AND kind=? AND provider=? AND access_status='available'",
                Integer.class, source.id(), source.kind(), source.provider())), "article_identity_conflict");
        String dateValue = optional(source.row(), "receptionDate", null); LocalDate publishedDate = null;
        if (publicationClock == null && dateValue != null && source.kind().equals("disclosure")) {
            publishedDate = dateValue.matches("\\d{8}") ? LocalDate.parse(dateValue, java.time.format.DateTimeFormatter.BASIC_ISO_DATE) : LocalDate.parse(dateValue);
        }
        jdbc.update("""
                INSERT INTO article_versions(article_id,version,title,publisher,url,published_at,published_date,publication_precision,
                    raw_artifact_id,text_artifact_id,collected_at) VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(article_id,version) DO NOTHING
                """, source.id(), source.version(), source.title(), source.provider(), source.url(), publicationClock == null ? null : Timestamp.from(publicationClock), publishedDate,
                publicationClock != null ? "datetime" : publishedDate == null ? "unknown" : "day", rawId(namespace, source), textId(namespace, source), Timestamp.from(source.collected()));
        require(Integer.valueOf(1).equals(jdbc.queryForObject("SELECT count(*) FROM article_versions WHERE article_id=? AND version=? AND title=? AND url=? AND text_artifact_id=? AND raw_artifact_id=?",
                Integer.class, source.id(), source.version(), source.title(), source.url(), textId(namespace, source), rawId(namespace, source))), "article_version_conflict");
        jdbc.update("UPDATE articles SET current_version=? WHERE id=? AND current_version IS NULL", source.version(), source.id());
    }

    private void registerEvidence(String namespace, Citation citation, Instant at) {
        String locators = json(StrictJson.newArray().add("body:" + citation.start() + ":" + citation.end()));
        jdbc.update("""
                INSERT INTO evidence(id,article_id,article_version,text_artifact_id,summary_analysis_id,quote,start_offset,end_offset,
                    offset_unit,input_kind,raw_locator_ids,quote_verified,verification_artifact_id,verified_at,created_at)
                VALUES(?,?,?,?,NULL,?,?,?,'unicode_code_point','body',?::jsonb,true,?,?,?) ON CONFLICT(id) DO NOTHING
                """, citation.id(), citation.source().id(), citation.source().version(), textId(namespace, citation.source()),
                citation.quote(), citation.start(), citation.end(), locators,
                exactId(namespace, citation), Timestamp.from(at), Timestamp.from(at));
        require(Integer.valueOf(1).equals(jdbc.queryForObject("SELECT count(*) FROM evidence WHERE id=? AND article_id=? AND article_version=? AND text_artifact_id=? AND quote=? AND start_offset=? AND end_offset=? AND quote_verified IS TRUE AND verification_artifact_id=?",
                Integer.class, citation.id(), citation.source().id(), citation.source().version(), textId(namespace, citation.source()),
                citation.quote(), citation.start(), citation.end(), exactId(namespace, citation))), "evidence_identity_conflict");
    }

    private void registerRound(Round round) {
        String payload = json(round.payload()), snapshot = json(round.snapshot()), comparison = round.comparison() == null ? null : json(round.comparison());
        jdbc.update("""
                INSERT INTO briefing_rounds(id,round_date,edition,scheduled_at,window_from,window_to,open_start,status,review_revision,
                    rule_revision,graph_version_id,published_payload,public_snapshot,schema_version,payload_sha256,comparison_snapshot,
                    generated_at,published_at,created_at) VALUES(?,?,?,?,?,?,false,'published',0,NULL,NULL,?::jsonb,?::jsonb,
                    'zoop-briefing-replay-v1',encode(sha256(convert_to((?::jsonb)::text,'UTF8')),'hex'),?::jsonb,?,?,?)
                    ON CONFLICT(id) DO NOTHING
                """, round.id(), round.date(), round.edition(), Timestamp.from(round.scheduled()), Timestamp.from(round.start()),
                Timestamp.from(round.scheduled()), payload, snapshot, payload, comparison,
                Timestamp.from(round.generated()), Timestamp.from(round.published()), Timestamp.from(round.published()));
        require(Integer.valueOf(1).equals(jdbc.queryForObject("""
                SELECT count(*) FROM briefing_rounds WHERE id=? AND published_payload=?::jsonb AND public_snapshot=?::jsonb
                    AND comparison_snapshot IS NOT DISTINCT FROM ?::jsonb AND graph_version_id IS NULL
                    AND payload_sha256=encode(sha256(convert_to(published_payload::text,'UTF8')),'hex')
                """, Integer.class, round.id(), payload, snapshot, comparison)), "round_identity_conflict");
    }

    private void registerHeld(Held round, Instant created) {
        String snapshot = json(round.snapshot());
        jdbc.update("""
                INSERT INTO briefing_rounds(id,round_date,edition,scheduled_at,window_from,window_to,open_start,status,
                    stages,failure_reason,public_snapshot,created_at)
                VALUES(?,?,?,?,?,?,false,?,?::jsonb,'simulation_not_published',?::jsonb,?) ON CONFLICT(id) DO NOTHING
                """, round.id(), round.date(), round.edition(), Timestamp.from(round.cutoff()), Timestamp.from(round.from()),
                Timestamp.from(round.cutoff()), round.status(), json(StrictJson.newObject().put("simulation", "held")), snapshot, Timestamp.from(created));
        require(Integer.valueOf(1).equals(jdbc.queryForObject("""
                SELECT count(*) FROM briefing_rounds WHERE id=? AND round_date=? AND edition=? AND status=?
                    AND window_from=? AND window_to=? AND published_at IS NULL AND published_payload IS NULL
                    AND public_snapshot=?::jsonb AND graph_version_id IS NULL
                """, Integer.class, round.id(), round.date(), round.edition(), round.status(), Timestamp.from(round.from()),
                Timestamp.from(round.cutoff()), snapshot)), "held_round_identity_conflict");
    }

    private static void sourceBlobs(String namespace, String sourceSha, Map<String, Source> documents,
            Map<String, Citation> citations, Map<String, Blob> blobs) {
        for (Source source : documents.values()) {
            blobs.put(rawId(namespace, source), blob("raw_document", source.raw()));
            blobs.put(textId(namespace, source), new Blob("extracted_text", source.body().getBytes(StandardCharsets.UTF_8), "text/plain; charset=utf-8"));
        }
        for (Citation citation : citations.values()) {
            ObjectNode exact = StrictJson.newObject().put("schemaVersion", "zoop-briefing-replay-exact-v1")
                    .put("sourceFileSha256", sourceSha).put("documentId", citation.source().id())
                    .put("documentVersion", citation.source().version()).put("bodySha256", citation.source().bodySha())
                    .put("evidenceId", citation.id()).put("quote", citation.quote()).put("start", citation.start())
                    .put("end", citation.end()).put("offsetUnit", "unicode_code_point").put("verified", true);
            blobs.put(exactId(namespace, citation), blob("exact_receipt", StrictJson.write(exact)));
        }
    }

    private String sqlDigest(JsonNode value) {
        return jdbc.queryForObject("SELECT encode(sha256(convert_to((?::jsonb)::text,'UTF8')),'hex')", String.class, json(value));
    }
    private static String rawId(String namespace, Source source) { return namespace + "-raw-" + Canonical.sha256(source.key()).substring(0, 24); }
    private static String textId(String namespace, Source source) { return namespace + "-text-" + Canonical.sha256(source.key()).substring(0, 24); }
    private static String exactId(String namespace, Citation citation) { return namespace + "-exact-" + Canonical.sha256(citation.id()).substring(0, 24); }
    private static String grantId(String run, Source source) { return "development-replay-" + Canonical.sha256(run + "\u0000" + source.key()).substring(0, 32); }
    private static String json(JsonNode value) { return new String(StrictJson.write(value), StandardCharsets.UTF_8); }
    private static Blob blob(String kind, byte[] bytes) { return new Blob(kind, bytes, "application/json"); }
    private static String text(StrictJson.Obj obj, String name) { String value = obj.string(name); require(!value.isBlank(), "blank_" + name); return value; }
    private static String optional(StrictJson.Obj obj, String name, String fallback) { return obj.has(name) && !obj.isNull(name) ? obj.string(name) : fallback; }
    private static void cited(List<String> refs, Set<String> allowed) { require(!refs.isEmpty() && allowed.containsAll(refs) && new HashSet<>(refs).size() == refs.size(), "foreign_or_duplicate_evidence"); }
    private static Long token(JsonNode value) { if (value.isNull()) return null; require(value.isIntegralNumber() && value.canConvertToLong() && value.longValue() >= 0, "invalid_usage"); return value.longValue(); }
    private static void failure(ArrayNode failures, String section, String code, String message) {
        failures.addObject().put("section", section).put("code", code).put("message", message).put("retryable", false).putNull("asOf");
    }
    private static byte[] read(Path path) {
        try (var stream = Files.newInputStream(path, LinkOption.NOFOLLOW_LINKS)) {
            byte[] bytes = stream.readNBytes(MAX_FILE_BYTES + 1); require(bytes.length <= MAX_FILE_BYTES, "private_file_too_large"); return bytes;
        } catch (IOException error) { throw new IllegalStateException("Briefing replay private input unavailable", error); }
    }
    private static void checkExisting(Path path, byte[] expected) {
        if (Files.exists(path, LinkOption.NOFOLLOW_LINKS)) {
            try {
                require(Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS)
                        && Files.getPosixFilePermissions(path, LinkOption.NOFOLLOW_LINKS).equals(PosixFilePermissions.fromString("rw-------"))
                        && Arrays.equals(read(path), expected), "private_output_conflict");
            } catch (IOException error) { throw new IllegalStateException("Briefing replay private output unavailable", error); }
        }
    }
    private static void publish(Path path, byte[] bytes) {
        checkExisting(path, bytes); if (Files.exists(path, LinkOption.NOFOLLOW_LINKS)) return;
        Path temporary = null;
        try {
            temporary = Files.createTempFile(path.getParent(), ".briefing-replay-", ".tmp",
                    PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")));
            try (var channel = java.nio.channels.FileChannel.open(temporary, Set.of(StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS))) {
                var buffer = java.nio.ByteBuffer.wrap(bytes); while (buffer.hasRemaining()) channel.write(buffer); channel.force(true);
            }
            try { Files.createLink(path, temporary); }
            catch (java.nio.file.FileAlreadyExistsException collision) { checkExisting(path, bytes); }
            try (var parent = java.nio.channels.FileChannel.open(path.getParent(), StandardOpenOption.READ)) { parent.force(true); }
        } catch (IOException error) { throw new IllegalStateException("Briefing replay private output unavailable; retry the identical bundle", error); }
        finally {
            if (temporary != null) try { Files.deleteIfExists(temporary); } catch (IOException ignored) { /* Only our own temporary. */ }
        }
    }
    private static void rejectCredentialFields(JsonNode value) {
        if (value.isObject()) {
            for (String name : value.propertyNames()) {
                String key = name.toLowerCase(java.util.Locale.ROOT).replace("_", "").replace("-", "");
                require(!Set.of("apikey", "apitoken", "token", "accesstoken", "refreshtoken", "authorizationtoken", "password", "clientsecret", "secret", "secretkey").contains(key), "credential_field");
                rejectCredentialFields(value.get(name));
            }
        } else if (value.isArray()) for (JsonNode child : value) rejectCredentialFields(child);
    }
    private static void require(boolean ok, String code) { if (!ok) throw new IllegalArgumentException("Briefing replay rejected: " + code); }
    private record Blob(String kind, byte[] bytes, String mediaType) { }
    private record Source(String id, String version, String bodySha, String body, String url, String title, String provider,
            String kind, Instant collected, StrictJson.Obj row, byte[] raw) { String key() { return id + "\u0000" + bodySha; } }
    private record Citation(String id, Source source, String quote, int start, int end) { }
    private record Company(String id, String name) { }
    private record Issue(String id, int rank, String reason, List<Company> companies, List<Citation> citations) { }
    private record Round(String id, LocalDate date, String edition, Instant scheduled, Instant start, Instant generated,
            Instant published, ObjectNode payload, ObjectNode snapshot, ObjectNode comparison) { }
    private record Held(String id, LocalDate date, String edition, Instant from, Instant cutoff, String status, ObjectNode snapshot) { }
}
