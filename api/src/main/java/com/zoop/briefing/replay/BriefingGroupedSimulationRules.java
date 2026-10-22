package com.zoop.briefing.replay;

import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

/** Opt-in historical issue archive import. It never changes the operational approval or graph contract. */
final class BriefingGroupedSimulationRules {
    static final String SCHEMA = "zoop-briefing-grouped-simulation-v1";
    static final String SELECTION_STAGE = "grouped_issue_selection";
    private static final int LIMIT = 128 * 1024 * 1024;

    record UnknownCall(String digest, byte[] request, byte[] reservation) { }
    record Archive(byte[] bytes, StrictJson.Obj root, Map<String, StrictJson.Obj> issues,
            Map<String, JsonNode> sources, PublicationClockRegistry clocks, List<UnknownCall> unknownCalls) { }

    static Archive archive(StrictJson.Obj bundle, Path output, Map<String, JsonNode> sources,
            PublicationClockRegistry clocks) {
        byte[] bytes = read(output.resolve("grouped-issues.json"));
        require(Canonical.sha256(bytes).equals(bundle.string("groupArchiveSha256")), "archive_digest");
        StrictJson.Obj archive = StrictJson.parseObject(bytes);
        require("zoop-grouped-issues-v1".equals(archive.string("schemaVersion"))
                && bundle.string("sourceFileSha256").equals(archive.string("sourceFileSha256")), "archive_source");
        String companyPolicy = archive.has("identity") && archive.object("identity").has("companyProjectionVersion")
                ? archive.object("identity").stringOrNull("companyProjectionVersion") : null;
        require(companyPolicy == null || "canonical-evidence-v1".equals(companyPolicy), "archive_company_projection_policy");
        Map<String, StrictJson.Obj> issues = new LinkedHashMap<>(); Set<String> mentions = new HashSet<>();
        for (StrictJson.Obj issue : archive.objects("issues")) {
            require(issues.putIfAbsent(issue.string("issueId"), issue) == null, "duplicate_issue");
            for (StrictJson.Obj mention : issue.objects("mentions")) {
                require(mentions.add(mention.string("mentionId")), "duplicate_mention");
                require((companyPolicy != null) == mention.has("companyProjection"), "archive_company_projection_declaration");
                companyEligible(mention);
                String key = mention.string("articleId") + "\u0000" + mention.string("bodySha256");
                JsonNode source = sources.get(key); PublicationClockRegistry.Clock clock = clocks.verified.get(key);
                require(source != null && clock != null && ("sha256-" + mention.string("bodySha256")).equals(mention.string("articleVersion"))
                        && clock.publishedAt().equals(Instant.parse(mention.string("publishedAt"))), "mention_source_clock");
                require(!mention.objects("evidence").isEmpty(), "mention_evidence");
                for (StrictJson.Obj evidence : mention.objects("evidence")) exact(evidence, mention, source);
                for (StrictJson.Obj company : mention.objects("companies")) {
                    require(!company.string("companyId").isBlank() && !company.string("name").isBlank()
                            && !company.objects("evidence").isEmpty(), "company_evidence");
                    for (StrictJson.Obj evidence : company.objects("evidence")) exact(evidence, mention, source);
                }
            }
        }
        require(archive.array("receipts").equals(bundle.array("groupingReceipts")), "archive_receipt_ownership");
        List<UnknownCall> unknownCalls = new ArrayList<>(); Set<String> usedDocuments = new HashSet<>();
        issues.values().forEach(issue -> issue.objects("mentions").forEach(m -> usedDocuments.add(m.string("articleId"))));
        for (StrictJson.Obj receipt : archive.objects("receipts")) {
            recording(receipt, output, false);
            if ("unknown".equals(receipt.string("status"))) unknownCalls.add(unknown(receipt, archive, usedDocuments, output));
        }
        return new Archive(bytes, archive, issues, sources, clocks, List.copyOf(unknownCalls));
    }

    /** An unanswered paid reservation is audit material. Its affected incoming documents stay outside accepted issues. */
    private static UnknownCall unknown(StrictJson.Obj receipt, StrictJson.Obj archive, Set<String> usedDocuments, Path output) {
        require(!receipt.bool("usageKnown") && receipt.isNull("inputTokens") && receipt.isNull("outputTokens")
                && receipt.isNull("responseId") && (!receipt.has("responseSha256") || receipt.isNull("responseSha256"))
                && (!receipt.has("httpStatus") || receipt.isNull("httpStatus"))
                && (!receipt.has("actualCostKnown") || !receipt.bool("actualCostKnown"))
                && (!receipt.has("actualCost") || receipt.isNull("actualCost")), "unknown_receipt_cannot_claim_response_or_usage");
        String digest = receipt.string("requestDigest");
        byte[] requestBytes = read(output.resolve("calls").resolve(digest + ".request.json"));
        byte[] reservationBytes = read(output.resolve("calls").resolve(digest + ".pending.json"));
        StrictJson.Obj request = StrictJson.parseObject(requestBytes), reservation = StrictJson.parseObject(reservationBytes);
        require(!Files.exists(output.resolve("calls").resolve(digest + ".complete.json"), LinkOption.NOFOLLOW_LINKS)
                && !Files.exists(output.resolve("calls").resolve(digest + ".response.json"), LinkOption.NOFOLLOW_LINKS)
                && digest.equals(Canonical.sha256(requestBytes)) && digest.equals(reservation.string("requestDigest"))
                && receipt.string("stage").equals(reservation.string("stage")) && receipt.string("model").equals(reservation.string("model"))
                && Canonical.sha256(request.string("instructions")).equals(reservation.string("promptSha256"))
                && Canonical.digest(request.object("text").object("format").object("schema").node()).equals(reservation.string("schemaSha256"))
                && request.count("max_output_tokens") == reservation.count("maxOutputTokens")
                && reservation.count("reservedInputTokenBound") > 0, "unknown_reservation_binding");
        StrictJson.Obj input = StrictJson.parseObject(request.string("input")); Set<String> affected = new HashSet<>();
        switch (receipt.string("stage")) {
            case "issue_extraction" -> input.objects("documents").forEach(d -> affected.add(d.object("article").string("article_id")));
            case "issue_grounding" -> input.objects("articles").forEach(a -> affected.add(a.string("article_id")));
            case "issue_comparison" -> input.object("pairs").node().propertyNames().forEach(key ->
                    affected.add(input.object("pairs").object(key).object("input").object("mention").string("article_id")));
            default -> require(false, "unknown_grouping_stage");
        }
        require(!affected.isEmpty() && affected.stream().noneMatch(usedDocuments::contains), "unknown_documents_cannot_support_accepted_issues");
        Set<String> held = new HashSet<>();
        for (StrictJson.Obj hold : archive.objects("held")) if (hold.has("requestDigest") && digest.equals(hold.string("requestDigest"))) {
            require(!hold.bool("usageKnown") && receipt.string("stage").equals(hold.string("stage")), "unknown_hold_binding");
            held.add(hold.string("articleId"));
        }
        require(held.containsAll(affected), "unknown_documents_require_explicit_hold");
        return new UnknownCall(digest, requestBytes, reservationBytes);
    }

    /** Optional legacy-compatible identity projection; it is never an event or same-legal-entity approval. */
    static boolean companyEligible(StrictJson.Obj mention) {
        if (!mention.has("companyProjection")) return true;
        StrictJson.Obj projection = mention.object("companyProjection");
        require("canonical-evidence-v1".equals(projection.string("policy"))
                && (!projection.has("version") || "canonical-evidence-v1".equals(projection.string("version"))), "company_projection_policy");
        List<StrictJson.Obj> linked = new ArrayList<>(); boolean eligible = true;
        Set<String> evidenceIds = new HashSet<>(); mention.objects("evidence").forEach(e -> evidenceIds.add(e.string("evidenceId")));
        for (StrictJson.Obj audit : projection.objects("audit")) {
            String status = audit.string("status"), supplied = audit.stringOrNull("suppliedCompanyId");
            require(Set.of("linked_name_match", "linked_exact_evidence_match", "not_indexed", "excluded_unknown_company_id",
                    "excluded_no_exact_mention_evidence", "excluded_company_identity_unconfirmed").contains(status), "company_projection_status");
            require(!audit.string("suppliedName").isBlank() && evidenceIds.containsAll(audit.strings("matchedEvidenceIds")), "company_projection_evidence");
            StrictJson.Obj raw = audit.object("rawParticipant");
            require(java.util.Objects.equals(supplied, raw.stringOrNull("company_id")) && audit.string("suppliedName").equals(raw.string("name"))
                    && audit.string("suppliedRole").equals(raw.string("role")), "company_projection_reported_identity");
            if (status.startsWith("linked_")) {
                require(supplied != null && !supplied.isBlank() && audit.stringOrNull("canonicalName") != null
                        && (!audit.has("sameLegalEntityEstablished") || !audit.bool("sameLegalEntityEstablished")), "company_projection_link");
                if ("linked_exact_evidence_match".equals(status)) require(!audit.strings("matchedEvidenceIds").isEmpty(), "company_projection_link_evidence");
                linked.add(audit);
            } else if ("not_indexed".equals(status)) require(supplied == null && audit.isNull("canonicalName")
                    && audit.strings("matchedEvidenceIds").isEmpty(), "company_projection_unindexed");
            else {
                eligible = false;
                if ("excluded_unknown_company_id".equals(status)) require(supplied != null && audit.isNull("canonicalName"), "company_projection_unknown_identity");
            }
        }
        require(projection.bool("briefingEligible") == eligible, "company_projection_eligibility");
        if (projection.has("status")) require((eligible ? "eligible" : "quarantined").equals(projection.string("status")), "company_projection_overall_status");
        List<StrictJson.Obj> companies = mention.objects("companies"); require(companies.size() == linked.size(), "company_projection_link_population");
        for (int index = 0; index < companies.size(); index++) {
            StrictJson.Obj company = companies.get(index), audit = linked.get(index);
            require(company.string("companyId").equals(audit.string("suppliedCompanyId")) && company.string("name").equals(audit.string("canonicalName"))
                    && company.string("role").equals(audit.string("suppliedRole")), "company_projection_canonical_link");
        }
        return eligible;
    }

    private static void exact(StrictJson.Obj evidence, StrictJson.Obj mention, JsonNode source) {
        String body = source.path("body").stringValue(); int start = evidence.count("start"), end = evidence.count("end");
        require(!evidence.string("evidenceId").isBlank() && evidence.string("articleId").equals(mention.string("articleId"))
                && evidence.string("articleVersion").equals(mention.string("articleVersion"))
                && start < end && end <= body.codePointCount(0, body.length())
                && evidence.string("quote").equals(body.substring(body.offsetByCodePoints(0, start), body.offsetByCodePoints(0, end))), "archive_exact_quote");
    }

    static void round(StrictJson.Obj bundle, StrictJson.Obj round, Archive archive,
            Map<String, JsonNode> receipts, Path output, ArrayNode history) {
        require(bundle.string("groupArchiveSha256").equals(round.object("identity").string("groupArchiveSha256")), "identity_archive");
        Set<String> stages = Set.of(SELECTION_STAGE, "round_simulation_" + round.string("edition") + "_generation",
                "round_simulation_" + round.string("edition") + "_verification");
        for (JsonNode value : receipts.values()) require(stages.contains(StrictJson.Obj.of(value).string("stage")), "round_receipt_scope");
        Instant from = Instant.parse(round.object("window").string("from")), to = Instant.parse(round.object("window").string("to"));
        Map<String, StrictJson.Obj> expected = new LinkedHashMap<>();
        for (var entry : archive.issues().entrySet()) {
            List<StrictJson.Obj> available = entry.getValue().objects("mentions").stream()
                    .filter(m -> !Instant.parse(m.string("publishedAt")).isAfter(to)).toList();
            // A later quarantined member cannot remove an otherwise eligible earlier round's issue.
            if (available.stream().allMatch(BriefingGroupedSimulationRules::companyEligible)
                    && available.stream().anyMatch(m -> Instant.parse(m.string("publishedAt")).isAfter(from)))
                expected.put(entry.getKey(), entry.getValue());
        }
        if (!round.has("groupedSelectionRequestDigest") || round.isNull("groupedSelectionRequestDigest")) {
            require(expected.isEmpty() && round.objects("selected").isEmpty(), "selection_recording_required"); return;
        }
        String key = round.string("groupedSelectionRequestDigest"); JsonNode node = receipts.get(key);
        require(node != null, "selection_receipt_missing"); StrictJson.Obj receipt = StrictJson.Obj.of(node);
        require(SELECTION_STAGE.equals(receipt.string("stage")), "selection_stage");
        boolean heldSelection = round.has("groupedUnresolvedPaidRequest")
                && SELECTION_STAGE.equals(round.object("groupedUnresolvedPaidRequest").string("stage"));
        Recording selected = heldSelection ? unresolvedSelection(round, receipt, output) : recording(receipt, output, true);
        StrictJson.Obj request = selected.input(); context(request, round);
        require(request.array("previousSelectedIssues").equals(history) && request.array("priorSelectedIssues").equals(history), "selection_previous_history");
        require(request.count("maximumIssues") == 3 && !request.bool("operationalCollectionGate")
                && !request.bool("historicalBodyUnchangedProven"), "selection_scope");
        Map<String, StrictJson.Obj> candidates = new LinkedHashMap<>();
        for (StrictJson.Obj candidate : request.objects("issues")) {
            String id = candidate.string("issueId"); require(candidates.putIfAbsent(id, candidate) == null && expected.containsKey(id), "candidate_identity");
            snapshot(candidate, expected.get(id), round, archive);
        }
        require(candidates.keySet().equals(expected.keySet()), "candidate_population");
        selectionCorrection(round, receipts, receipt, selected, output);
        boolean published = Set.of("SELECTED", "EMPTY_CONFIRMED").contains(round.string("selectionStatus"));
        // Invalid completed model answers are retained as audit for held rounds; they do not authorize publication.
        if (!published) return;
        StrictJson.Obj answer = selected.answer();
        answer.object("assessments").exactly(candidates.keySet());
        require(answer.objects("selected").size() <= 3, "selection_limit");
        Set<String> chosen = new HashSet<>();
        for (StrictJson.Obj choice : answer.objects("selected")) {
            String id = choice.string("issueId"); require(candidates.containsKey(id) && chosen.add(id), "selected_identity");
            StrictJson.Obj assessment = answer.object("assessments").object(id);
            require("SELECTABLE".equals(assessment.string("status")) && assessment.count("importance") >= 2, "selected_importance");
            if (assessment.count("importance") == 3) require(Set.of("BROAD_MARKET", "COMMON_POLICY").contains(assessment.string("scope"))
                    && !assessment.string("transmission").isBlank() && (!"BROAD_MARKET".equals(assessment.string("scope"))
                    || Set.copyOf(assessment.strings("affectedSectors")).size() >= 2), "broad_impact_proof");
        }
        Set<String> actual = new HashSet<>();
        for (StrictJson.Obj item : round.objects("selected")) {
            String id = item.string("issueId"); StrictJson.Obj candidate = candidates.get(id);
            require(chosen.contains(id) && actual.add(id) && candidate.node().equals(item.object("frozenGroupedIssueSnapshot").node())
                    && id.equals(item.string("eventKey")) && round.string("identitySha256").equals(item.string("selectionInputSha256"))
                    && candidate.string("asOfSnapshotSha256").equals(item.string("groupedIssueSnapshotSha256")), "selected_snapshot");
            StrictJson.Obj choice = answer.objects("selected").stream().filter(c -> id.equals(c.string("issueId"))).findFirst().orElseThrow();
            StrictJson.Obj assessment = answer.object("assessments").object(id);
            List<StrictJson.Obj> previousItems = new ArrayList<>();
            for (JsonNode previousNode : history) if (id.equals(StrictJson.Obj.of(previousNode).string("issueId"))) previousItems.add(StrictJson.Obj.of(previousNode));
            List<String> delta = choice.strings("deltaEvidenceIds");
            require(new HashSet<>(delta).size() == delta.size() && choice.strings("evidenceIds").containsAll(delta)
                    && candidate.strings("newEvidenceIds").containsAll(delta), "material_update_delta_binding");
            if (!previousItems.isEmpty()) {
                require("MATERIAL_UPDATE".equals(choice.string("novelty")) && !delta.isEmpty(), "repeat_requires_material_update");
                Map<String, StrictJson.Obj> deltaEvidence = evidence(candidate, "newMentions");
                require(delta.stream().anyMatch(e -> deltaEvidence.containsKey(e) && previousItems.stream()
                        .flatMap(old -> old.objects("sources").stream()).noneMatch(old -> e.equals(old.string("evidenceId"))
                                || deltaEvidence.get(e).string("quote").equals(old.string("quote")))), "repeat_requires_new_fact_evidence");
            }
            require(choice.string("title").equals(item.string("title")) && assessment.string("reason").equals(item.string("reason"))
                    && assessment.count("importance") == item.count("importance") && assessment.count("priority") == item.count("score"), "selected_answer");
            Set<String> evidenceIds = new HashSet<>(); Map<String, StrictJson.Obj> evidence = evidence(candidate, "newMentions");
            for (StrictJson.Obj source : item.objects("sources")) {
                String evidenceId = source.string("evidenceId");
                require(evidenceIds.add(evidenceId) && evidence.containsKey(evidenceId)
                        && source.node().equals(evidence.get(evidenceId).node()), "selected_current_evidence");
            }
            require(!evidenceIds.isEmpty() && evidenceIds.equals(Set.copyOf(choice.strings("evidenceIds"))), "selected_evidence_membership");
            Map<String, StrictJson.Obj> companyCatalog = new LinkedHashMap<>();
            Map<String, Set<String>> companyEvidence = new LinkedHashMap<>();
            for (String field : List.of("backgroundMentions", "newMentions")) for (StrictJson.Obj mention : candidate.objects(field))
                for (StrictJson.Obj company : mention.objects("companies")) {
                    String companyId = company.string("companyId");
                    StrictJson.Obj previous = companyCatalog.putIfAbsent(companyId, company);
                    require(previous == null || previous.string("name").equals(company.string("name")), "selected_company_identity");
                    companyEvidence.computeIfAbsent(companyId, ignored -> new HashSet<>()).addAll(company.strings("evidenceIds"));
                }
            List<String> companyIds = new ArrayList<>(), companyNames = new ArrayList<>();
            for (StrictJson.Obj company : item.objects("companyLinks")) {
                String companyId = company.string("companyId"); StrictJson.Obj known = companyCatalog.get(companyId);
                require(known != null && !companyIds.contains(companyId) && known.string("name").equals(company.string("name"))
                        && known.raw("role").equals(company.raw("role")), "selected_company_binding");
                Set<String> expectedLinks = new HashSet<>(companyEvidence.get(companyId)); expectedLinks.retainAll(evidenceIds);
                require(!expectedLinks.isEmpty() && expectedLinks.equals(Set.copyOf(company.strings("evidenceIds"))), "selected_company_citations");
                companyIds.add(companyId); companyNames.add(company.string("name"));
            }
            require(companyIds.equals(choice.strings("companyIds")) && companyNames.equals(item.strings("companyNames")), "selected_company_membership");
        }
        require(actual.equals(chosen), "selected_population");
        StrictJson.Obj result = round.object("result");
        String generation = "round_simulation_" + round.string("edition") + "_generation";
        String verification = "round_simulation_" + round.string("edition") + "_verification";
        Recording generated = phase(receipts, result.string("generationRequestDigest"), generation, output);
        Recording verified = phase(receipts, result.string("verificationRequestDigest"), verification, output);
        for (Recording call : List.of(generated, verified)) {
            context(call.input(), round);
            require(call.input().array("priorSelectedIssues").equals(history), "generation_previous_history");
            require(call.input().array("selected").equals(round.array("selected")) && round.string("edition").equals(call.input().string("edition")), "generation_selected_binding");
        }
        JsonNode items = normalize(generated.answer().raw("items"), round.objects("selected").stream().map(i -> i.string("issueId")).toList());
        require(items.equals(result.array("items")) && verified.input().object("draft").array("items").equals(items), "generated_answer_binding");
        List<String> targets = new ArrayList<>();
        for (JsonNode value : items) {
            StrictJson.Obj item = StrictJson.Obj.of(value); targets.add(item.string("issueId") + ":title");
            for (int index = 0; index < item.array("claims").size(); index++) targets.add(item.string("issueId") + ":claim:" + index);
        }
        require(normalize(verified.answer().raw("checks"), targets).equals(result.object("verification").array("checks")), "verification_answer_binding");
        Set<String> usage = new HashSet<>();
        for (StrictJson.Obj finalReceipt : result.objects("usage")) {
            String digest = finalReceipt.string("requestDigest"); require(usage.add(digest)
                    && finalReceipt.node().equals(receipts.get(digest)), "result_receipt_binding");
        }
        require(usage.equals(Set.of(result.string("generationRequestDigest"), result.string("verificationRequestDigest"))), "result_usage_pair");
    }

    /** A single corrected selection may alter only its explicit correction block, never the frozen evidence/history. */
    private static void selectionCorrection(StrictJson.Obj round, Map<String, JsonNode> receipts, StrictJson.Obj finalReceipt,
            Recording selected, Path output) {
        Map<String, StrictJson.Obj> attempts = new LinkedHashMap<>();
        for (JsonNode value : receipts.values()) {
            StrictJson.Obj receipt = StrictJson.Obj.of(value);
            if (SELECTION_STAGE.equals(receipt.string("stage"))) attempts.put(receipt.string("requestDigest"), receipt);
        }
        require(!attempts.isEmpty() && attempts.size() <= 2, "selection_correction_limit");
        if (!selected.input().has("selectionCorrection")) {
            require(attempts.size() == 1, "selection_orphan_prior_attempt"); return;
        }
        StrictJson.Obj correction = selected.input().object("selectionCorrection");
        require(correction.count("attempt") == 1 && correction.bool("sameFrozenInputs")
                && !correction.string("failure").isBlank(), "selection_correction_scope");
        String originalDigest = correction.string("originalRequestDigest");
        StrictJson.Obj originalReceipt = attempts.get(originalDigest);
        require(attempts.size() == 2 && originalReceipt != null && !originalDigest.equals(finalReceipt.string("requestDigest"))
                && correction.string("originalResponseSha256").equals(originalReceipt.string("responseSha256")), "selection_correction_original_receipt");
        Recording original = recording(originalReceipt, output, true);
        require(!original.input().has("selectionCorrection") && original.answer().node().equals(correction.object("previousReply").node()), "selection_correction_original_reply");
        ObjectNode baseline = (ObjectNode) selected.input().node().deepCopy(); baseline.remove("selectionCorrection");
        require(baseline.equals(original.input().node()), "selection_correction_frozen_inputs");
        ObjectNode originalRequest = (ObjectNode) StrictJson.parseObject(read(output.resolve("calls").resolve(originalDigest + ".request.json"))).node().deepCopy();
        ObjectNode correctedRequest = (ObjectNode) StrictJson.parseObject(read(output.resolve("calls").resolve(finalReceipt.string("requestDigest") + ".request.json"))).node().deepCopy();
        originalRequest.remove("input"); correctedRequest.remove("input");
        require(originalRequest.equals(correctedRequest), "selection_correction_provider_contract");
        context(original.input(), round);
    }

    private static Recording phase(Map<String, JsonNode> receipts, String digest, String stage, Path output) {
        require(receipts.containsKey(digest), "phase_receipt_missing"); StrictJson.Obj receipt = StrictJson.Obj.of(receipts.get(digest));
        require(stage.equals(receipt.string("stage")), "phase_stage"); return recording(receipt, output, true);
    }

    private static void context(StrictJson.Obj input, StrictJson.Obj round) {
        require(round.string("identitySha256").equals(input.string("contextSha256"))
                && round.object("identity").node().equals(input.object("context").node()), "request_context_binding");
        StrictJson.Obj previous = round.object("previous");
        if ("available".equals(previous.string("status"))) require(!input.isNull("simulatedPreviousOutput")
                && previous.string("resultSha256").equals(Canonical.digest(input.object("simulatedPreviousOutput").node())), "request_previous_result_binding");
        else require(input.isNull("simulatedPreviousOutput"), "request_previous_result_unavailable");
    }

    private static void snapshot(StrictJson.Obj candidate, StrictJson.Obj issue, StrictJson.Obj round, Archive archive) {
        require(candidate.object("window").node().equals(round.object("window").node())
                && archive.root().string("sourceFileSha256").equals(candidate.string("sourceFileSha256"))
                && candidate.bool("historicalSimulation") == !round.has("localCollection") && !candidate.bool("operationalCollectionGate")
                && !candidate.bool("historicalBodyUnchangedProven"), "snapshot_scope");
        ObjectNode identity = (ObjectNode) candidate.node().deepCopy(); identity.remove("asOfSnapshotSha256");
        require(Canonical.digest(identity).equals(candidate.string("asOfSnapshotSha256")), "snapshot_digest");
        Instant from = Instant.parse(round.object("window").string("from")), to = Instant.parse(round.object("window").string("to"));
        Map<String, StrictJson.Obj> expected = new LinkedHashMap<>();
        issue.objects("mentions").stream().filter(m -> !Instant.parse(m.string("publishedAt")).isAfter(to))
                .forEach(m -> expected.put(m.string("mentionId"), m));
        Set<String> seen = new HashSet<>();
        for (String field : List.of("newMentions", "backgroundMentions")) for (StrictJson.Obj mention : candidate.objects(field)) {
            StrictJson.Obj original = expected.get(mention.string("mentionId"));
            require(original != null && seen.add(mention.string("mentionId")), "snapshot_mention_identity");
            for (String name : List.of("articleId", "articleVersion", "bodySha256", "publishedAt", "title", "action", "target", "eventTime", "keywords"))
                require(original.raw(name).equals(mention.raw(name)), "snapshot_mention_binding");
            boolean fresh = Instant.parse(mention.string("publishedAt")).isAfter(from);
            require(fresh == "newMentions".equals(field) && fresh == mention.bool("newInRound"), "snapshot_mention_time");
            Map<String, StrictJson.Obj> allowed = new LinkedHashMap<>();
            original.objects("evidence").forEach(e -> allowed.put(e.string("evidenceId"), e));
            original.objects("companies").forEach(c -> c.objects("evidence").forEach(e -> allowed.put(e.string("evidenceId"), e)));
            Set<String> actual = new HashSet<>();
            for (StrictJson.Obj proof : mention.objects("evidence")) {
                String id = proof.string("evidenceId"); require(actual.add(id) && allowed.containsKey(id), "snapshot_evidence_identity");
                StrictJson.Obj old = allowed.get(id);
                for (String name : List.of("quote", "start", "end")) require(old.raw(name).equals(proof.raw(name)), "snapshot_evidence_binding");
                require(original.string("articleId").equals(proof.string("documentId"))
                        && original.string("articleVersion").equals(proof.string("documentVersion"))
                        && original.string("bodySha256").equals(proof.string("bodySha256")), "snapshot_source_binding");
                PublicationClockRegistry.Clock clock = archive.clocks().verified.get(original.string("articleId") + "\u0000" + original.string("bodySha256"));
                require(clock.original().equals(proof.object("publicationClock").node())
                        && clock.recordSha256().equals(proof.string("clockRecordSha256")), "snapshot_clock_binding");
            }
            require(actual.equals(allowed.keySet()), "snapshot_evidence_population");
            require(mention.objects("companies").size() == original.objects("companies").size(), "snapshot_company_population");
            for (int index = 0; index < mention.objects("companies").size(); index++) {
                StrictJson.Obj company = mention.objects("companies").get(index), old = original.objects("companies").get(index);
                for (String fieldName : List.of("companyId", "name", "role")) require(company.raw(fieldName).equals(old.raw(fieldName)), "snapshot_company_binding");
                require(company.strings("evidenceIds").equals(old.objects("evidence").stream().map(e -> e.string("evidenceId")).toList()), "snapshot_company_evidence");
            }
        }
        require(seen.equals(expected.keySet()) && !candidate.objects("newMentions").isEmpty(), "snapshot_asof_population");
        StrictJson.Obj earliest = expected.values().stream().min(java.util.Comparator
                .comparing((StrictJson.Obj m) -> Instant.parse(m.string("publishedAt")))
                .thenComparing(m -> m.string("mentionId"))).orElseThrow();
        require(earliest.string("title").equals(candidate.string("title")), "snapshot_title_asof");
        Map<String, StrictJson.Obj> newEvidence = evidence(candidate, "newMentions"), background = evidence(candidate, "backgroundMentions");
        Set<String> allEvidence = new HashSet<>(newEvidence.keySet()); allEvidence.addAll(background.keySet());
        require(Set.copyOf(candidate.strings("newEvidenceIds")).equals(newEvidence.keySet())
                && Set.copyOf(candidate.strings("asOfEvidenceIds")).equals(allEvidence), "snapshot_evidence_index");
    }

    private static Map<String, StrictJson.Obj> evidence(StrictJson.Obj candidate, String field) {
        Map<String, StrictJson.Obj> result = new LinkedHashMap<>();
        for (StrictJson.Obj mention : candidate.objects(field)) for (StrictJson.Obj proof : mention.objects("evidence"))
            require(result.putIfAbsent(proof.string("evidenceId"), proof) == null || result.get(proof.string("evidenceId")).node().equals(proof.node()), "evidence_identity_conflict");
        return result;
    }

    private static JsonNode normalize(JsonNode value, List<String> order) {
        if (value.isArray()) return value;
        StrictJson.Obj object = StrictJson.Obj.of(value).exactly(Set.copyOf(order)); ArrayNode normalized = StrictJson.newArray();
        order.forEach(id -> normalized.add(object.raw(id))); return normalized;
    }

    record Recording(StrictJson.Obj input, StrictJson.Obj answer) { }

    private static Recording unresolvedSelection(StrictJson.Obj round, StrictJson.Obj receipt, Path output) {
        StrictJson.Obj disposition = round.object("groupedUnresolvedPaidRequest");
        String digest = receipt.string("requestDigest");
        require("HELD_VALIDATION".equals(round.string("selectionStatus")) && round.objects("selected").isEmpty()
                && round.isNull("result") && round.isNull("resultSha256")
                && digest.equals(disposition.string("requestDigest")) && SELECTION_STAGE.equals(disposition.string("stage"))
                && "hold_without_retransmission".equals(disposition.string("operatorDisposition"))
                && disposition.bool("preexistingAtProcessStart") && !disposition.bool("usageKnown")
                && disposition.isNull("inputTokens") && disposition.isNull("outputTokens"), "unresolved_selection_disposition");
        require("unknown".equals(receipt.string("status")) && !receipt.bool("usageKnown")
                && receipt.isNull("inputTokens") && receipt.isNull("outputTokens")
                && (!receipt.has("responseSha256") || receipt.isNull("responseSha256"))
                && (!receipt.has("responseId") || receipt.isNull("responseId"))
                && !Files.exists(output.resolve("calls/" + digest + ".complete.json"))
                && !Files.exists(output.resolve("calls/" + digest + ".response.json")), "unresolved_selection_no_completed_answer");
        recording(receipt, output, false); // Validate the actual immutable request digest/provider identity.
        StrictJson.Obj request = StrictJson.parseObject(read(output.resolve("calls/" + digest + ".request.json")));
        StrictJson.Obj pending = StrictJson.parseObject(read(output.resolve("calls/" + digest + ".pending.json")));
        StrictJson.Obj format = request.object("text").object("format");
        require("gpt-6-luna".equals(request.string("model")) && "json_schema".equals(format.string("type")) && format.bool("strict")
                && digest.equals(pending.string("requestDigest")) && SELECTION_STAGE.equals(pending.string("stage"))
                && request.string("model").equals(pending.string("model"))
                && request.count("max_output_tokens") == pending.count("maxOutputTokens")
                && Canonical.sha256(request.string("instructions")).equals(pending.string("promptSha256"))
                && Canonical.digest(format.object("schema").node()).equals(pending.string("schemaSha256")), "unresolved_selection_reservation");
        Instant.parse(pending.string("createdAt"));
        StrictJson.Obj input = StrictJson.parseObject(request.string("input"));
        require(Canonical.sha256(request.string("instructions")).equals(input.object("context").object("promptArtifacts").string("grouped-selection.md")), "unresolved_selection_prompt");
        require(round.objects("receipts").stream().allMatch(r -> SELECTION_STAGE.equals(r.string("stage"))), "unresolved_selection_has_no_generation");
        return new Recording(input, null);
    }

    private static Recording recording(StrictJson.Obj receipt, Path output, boolean completed) {
        String digest = receipt.string("requestDigest"); require(digest.matches("[0-9a-f]{64}"), "receipt_digest");
        byte[] requestBytes = read(output.resolve("calls").resolve(digest + ".request.json"));
        require(digest.equals(Canonical.sha256(requestBytes)), "request_digest"); StrictJson.Obj request = StrictJson.parseObject(requestBytes);
        require(!request.bool("store") && receipt.string("model").equals(request.string("model"))
                && receipt.string("stage").equals(request.object("text").object("format").string("name")), "request_provider_binding");
        if (!completed && (!receipt.has("responseSha256") || receipt.isNull("responseSha256"))) return null;
        byte[] bytes = read(output.resolve("calls").resolve(digest + ".response.json"));
        require(Canonical.sha256(bytes).equals(receipt.string("responseSha256")), "response_digest"); StrictJson.Obj response = StrictJson.parseObject(bytes);
        if (!completed) return null; // Failed/incomplete grouping attempts remain raw accounting, not publication proof.
        require(Set.of("completed", "success", "succeeded").contains(receipt.string("status"))
                && receipt.bool("usageKnown") && receipt.count("httpStatus") == 200, "completed_receipt");
        require(response.string("status").equals(receipt.string("status")) && response.string("id").equals(receipt.string("responseId")), "response_identity");
        if (receipt.bool("usageKnown")) require(receipt.count("inputTokens") == response.object("usage").count("input_tokens")
                && receipt.count("outputTokens") == response.object("usage").count("output_tokens"), "response_usage");
        List<String> text = new ArrayList<>();
        for (StrictJson.Obj item : response.objects("output")) if ("message".equals(item.string("type")))
            for (StrictJson.Obj content : item.objects("content")) if ("output_text".equals(content.string("type"))) text.add(content.string("text"));
        require(text.size() == 1, "response_text");
        StrictJson.Obj input = StrictJson.parseObject(request.string("input"));
        String stage = receipt.string("stage");
        String prompt = SELECTION_STAGE.equals(stage) ? "grouped-selection.md"
                : stage.endsWith("_verification") ? "grouped-verification.md" : "grouped-generation-" + input.string("edition") + ".md";
        require(Canonical.sha256(request.string("instructions")).equals(input.object("context").object("promptArtifacts").string(prompt)), "request_prompt_binding");
        return new Recording(input, StrictJson.parseObject(text.getFirst()));
    }

    private static byte[] read(Path path) {
        try {
            require(Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS) && path.getParent().equals(path.getParent().toRealPath())
                    && Files.size(path) <= LIMIT, "artifact_file"); return Files.readAllBytes(path);
        } catch (IOException unavailable) { throw new IllegalArgumentException("Grouped simulation artifact unavailable", unavailable); }
    }

    private static void require(boolean valid, String code) {
        if (!valid) throw new IllegalArgumentException("Grouped simulation rejected: " + code);
    }
}
