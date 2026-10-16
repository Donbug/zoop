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
        Map<String, Issue> result = new LinkedHashMap<>();
        List<StrictJson.Obj> selected = bundle.objects("selected");
        require(!selected.isEmpty() && selected.size() <= 3, "selection_limit");
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
            require(!companies.isEmpty(), "company_required");
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
        jdbc.update("""
                INSERT INTO articles(id,kind,provider,provider_key,lineage_key,current_version,access_status,created_at)
                VALUES(?,?,?,NULL,NULL,NULL,'available',?) ON CONFLICT(id) DO NOTHING
                """, source.id(), source.kind(), source.provider(), Timestamp.from(source.collected()));
        require(Integer.valueOf(1).equals(jdbc.queryForObject("SELECT count(*) FROM articles WHERE id=? AND kind=? AND provider=? AND access_status='available'",
                Integer.class, source.id(), source.kind(), source.provider())), "article_identity_conflict");
        String dateValue = optional(source.row(), "receptionDate", null); LocalDate publishedDate = null;
        if (dateValue != null && source.kind().equals("disclosure")) {
            publishedDate = dateValue.matches("\\d{8}") ? LocalDate.parse(dateValue, java.time.format.DateTimeFormatter.BASIC_ISO_DATE) : LocalDate.parse(dateValue);
        }
        jdbc.update("""
                INSERT INTO article_versions(article_id,version,title,publisher,url,published_at,published_date,publication_precision,
                    raw_artifact_id,text_artifact_id,collected_at) VALUES(?,?,?,?,?,NULL,?,?,?,?,?) ON CONFLICT(article_id,version) DO NOTHING
                """, source.id(), source.version(), source.title(), source.provider(), source.url(), publishedDate,
                publishedDate == null ? "unknown" : "day", rawId(namespace, source), textId(namespace, source), Timestamp.from(source.collected()));
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
}
