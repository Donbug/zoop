package com.zoop.briefing.replay;

import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import java.io.IOException;
import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

/** A separate, source-bound item recovery layer; the original round chain is validated before it is applied. */
final class BriefingGroupedRecoveryRules {
    static final String SCHEMA = "zoop-briefing-item-recovery-v1";
    private static final List<String> FLAGS = List.of("typeAppropriate", "temporalAppropriate", "noUnsupportedNumbers",
            "noInvestmentAdvice", "conditionsPreserved", "atomicClaim");
    private static final List<String> PHASES = List.of("generation", "verification", "novelty");
    private static final String PREFIX = "briefing_item_recovery_";
    record Layer(byte[] baseBytes, byte[] editorialBytes, StrictJson.Obj root, Map<String, StrictJson.Obj> rounds,
            Map<String, JsonNode> receipts, Map<String, Recording> recordings) { }
    record Recording(StrictJson.Obj input, StrictJson.Obj answer, StrictJson.Obj receipt) { }

    static Layer load(StrictJson.Obj bundle, Path output, String inbox) {
        if (!bundle.has("briefingRecovery")) return null;
        require(BriefingGroupedSimulationRules.SCHEMA.equals(bundle.string("schemaVersion"))
                && !bundle.has("marketEnrichment"), "grouped_base_required");
        StrictJson.Obj layer = bundle.object("briefingRecovery");
        require(SCHEMA.equals(layer.string("schemaVersion")) && "item-recovery-v1".equals(layer.string("policyVersion"))
                && layer.string("runId").matches("[A-Za-z0-9_-]{1,96}")
                && !layer.string("runId").equals(bundle.string("runId")), "layer_identity");
        byte[] bytes = read(output.resolve("base-bundle-v2.json"));
        require(Canonical.sha256(bytes).equals(layer.string("baseBundleSha256")), "base_bytes_digest");
        ObjectNode base = (ObjectNode) bundle.node().deepCopy(); base.remove("briefingRecovery");
        require(base.equals(StrictJson.parseObject(bytes).node()), "base_json_unchanged");
        StrictJson.Obj authorization = layer.object("authorization");
        require("publication_clock_simulation".equals(authorization.string("scope"))
                && !authorization.bool("productionAuthorized") && inbox.equals(authorization.string("userInboxRef"))
                && bundle.string("sourceFileSha256").equals(authorization.string("sourceSha256")), "authorization");
        Set<String> names = new HashSet<>(); PHASES.forEach(p -> { names.add(p + ".md"); names.add(p + ".schema.json"); });
        StrictJson.Obj prompts = layer.object("promptArtifacts").exactly(names);
        for (String name : names) require(Canonical.sha256(resource(name)).equals(prompts.string(name)), "prompt_digest");
        Map<String, StrictJson.Obj> rounds = new LinkedHashMap<>();
        for (StrictJson.Obj round : layer.objects("rounds")) require(rounds.putIfAbsent(round.string("roundId"), round) == null, "duplicate_round");
        roundCoverage(bundle, rounds.keySet());
        Map<String, JsonNode> receipts = new LinkedHashMap<>(); Map<String, Recording> recordings = new LinkedHashMap<>();
        for (StrictJson.Obj receipt : layer.objects("receipts")) {
            String digest = receipt.string("requestDigest");
            require(receipts.putIfAbsent(digest, receipt.node()) == null, "duplicate_receipt");
            String phase = receipt.string("stage").replace(PREFIX, "");
            require(PHASES.contains(phase) && (PREFIX + phase).equals(receipt.string("stage")), "receipt_stage");
            recordings.put(digest, recording(receipt, output, true, prompts));
        }
        byte[] editorial = null;
        if (layer.has("editorialReview")) {
            StrictJson.Obj supplied = layer.object("editorialReview");
            if (supplied.isNull("sha256")) require(supplied.objects("holds").isEmpty(), "editorial_missing_file");
            else {
                editorial = read(output.resolve("editorial-review-holds.json")); StrictJson.Obj review = StrictJson.parseObject(editorial);
                require(Canonical.sha256(editorial).equals(supplied.string("sha256")) && review.array("holds").equals(supplied.array("holds"))
                        && inbox.equals(review.string("userInboxRef")) && !supplied.string("meaning").isBlank(), "editorial_file_binding");
            }
        }
        return new Layer(bytes, editorial, layer, rounds, receipts, recordings);
    }

    static void roundCoverage(StrictJson.Obj bundle, Set<String> recovered) {
        Set<String> expected = new HashSet<>();
        for (StrictJson.Obj round : bundle.objects("rounds"))
            require(expected.add(round.string("roundId")), "duplicate_base_round");
        int count = bundle.has("roundSeries") ? bundle.object("roundSeries").objects("rounds").size() : 14;
        require(count >= 1 && count <= 14 && expected.size() == count && recovered.equals(expected), "round_coverage");
    }

    static void validate(Layer layer, StrictJson.Obj bundle, Path output) {
        Map<String, JsonNode> baseReceipts = new LinkedHashMap<>();
        for (StrictJson.Obj receipt : bundle.objects("receipts")) baseReceipts.put(receipt.string("requestDigest"), receipt.node());
        for (String key : layer.receipts().keySet()) require(!baseReceipts.containsKey(key), "receipt_reuses_base_call");
        Set<String> reserved = new HashSet<>(baseReceipts.keySet());
        bundle.objects("groupingReceipts").forEach(r -> require(reserved.add(r.string("requestDigest")), "base_receipt_collision"));
        reserved.addAll(layer.receipts().keySet());
        require(layer.root().count("maximumPaidCallsIncludingPrior") <= 400
                && reserved.size() <= layer.root().count("maximumPaidCallsIncludingPrior"), "reservation_limit");
        ArrayNode history = StrictJson.newArray(); Set<String> used = new HashSet<>();
        Map<String, StrictJson.Obj> editorial = new LinkedHashMap<>(); Set<String> appliedEditorial = new HashSet<>();
        if (layer.root().has("editorialReview")) for (StrictJson.Obj hold : layer.root().object("editorialReview").objects("holds")) {
            String key = hold.string("roundId") + "\u0000" + hold.string("issueId");
            require(editorial.putIfAbsent(key, hold) == null && !hold.string("code").isBlank() && !hold.string("reason").isBlank()
                    && !hold.strings("evidenceIds").isEmpty(), "editorial_hold_identity");
        }
        for (StrictJson.Obj base : bundle.objects("rounds")) {
            StrictJson.Obj round = layer.rounds().get(base.string("roundId"));
            require(round != null && base.string("date").equals(round.string("date"))
                    && base.string("edition").equals(round.string("edition"))
                    && Canonical.digest(base.node()).equals(round.string("baseRoundSha256")), "round_base_binding");
            require(Set.of("SELECTED", "HELD_VALIDATION", "HELD_SOURCE_COVERAGE").contains(round.string("status")), "round_status");
            List<StrictJson.Obj> issues = round.objects("issues"); require(issues.size() <= 3, "issue_limit");
            Set<String> ids = new HashSet<>(); int previousRank = 0;
            ArrayNode expectedSelected = StrictJson.newArray(), expectedItems = StrictJson.newArray(), expectedChecks = StrictJson.newArray();
            Set<String> expectedUsage = new LinkedHashSet<>(), sourceDocuments = new HashSet<>();
            for (StrictJson.Obj issue : issues) {
                require(ids.add(issue.string("issueId")) && issue.count("originalRank") > previousRank, "issue_order");
                previousRank = issue.count("originalRank");
                require(Set.of("PASS", "WITHHELD", "REPEAT", "INVALID_SELECTION").contains(issue.string("status")), "issue_status");
                if ("INVALID_SELECTION".equals(issue.string("status"))) {
                    require(issue.isNull("selection") && issue.isNull("draft") && !issue.array("errors").isEmpty(), "invalid_selection_cannot_publish");
                    String key = issue.string("sourceSelectionRequestDigest");
                    require(key.equals(base.string("groupedSelectionRequestDigest")) && baseReceipts.containsKey(key), "invalid_selection_origin");
                    Recording original = recording(StrictJson.Obj.of(baseReceipts.get(key)), output, false, null);
                    require(original.answer().objects("selected").stream().anyMatch(c -> issue.string("issueId").equals(c.string("issueId"))), "invalid_selection_choice");
                    continue;
                }
                StrictJson.Obj selection = sourceSelection(base, issue, baseReceipts, output);
                String editorialKey = base.string("roundId") + "\u0000" + issue.string("issueId");
                StrictJson.Obj hold = editorial.get(editorialKey);
                if (hold != null) {
                    Set<String> sourceIds = new HashSet<>(); selection.objects("sources").forEach(s -> sourceIds.add(s.string("evidenceId")));
                    require(issue.has("editorialHold") && issue.object("editorialHold").node().equals(hold.node())
                            && "WITHHELD".equals(issue.string("status")) && issue.strings("errors").contains(hold.string("code"))
                            && sourceIds.containsAll(hold.strings("evidenceIds")), "editorial_hold_binding");
                    appliedEditorial.add(editorialKey);
                } else require(!issue.has("editorialHold") || issue.isNull("editorialHold"), "unregistered_editorial_hold");
                Recording draftCall = null;
                if (!issue.isNull("draft")) {
                    boolean original = "base".equals(issue.string("draftOrigin"));
                    require(original || "recovery".equals(issue.string("draftOrigin")), "draft_origin");
                    draftCall = originCall(layer, baseReceipts, issue.string("draftSourceRequestDigest"), original, output, used);
                    String phase = original ? "round_simulation_" + base.string("edition") + "_generation" : PREFIX + "generation";
                    require(phase.equals(draftCall.receipt().string("stage")), "draft_phase");
                    StrictJson.Obj draft = find(rows(draftCall.answer().raw("items")), "issueId", issue.string("issueId"));
                    ObjectNode normalized = (ObjectNode) draft.node().deepCopy(); normalized.put("rank", 1);
                    require(normalized.equals(issue.object("draft").node()), "draft_exact_response");
                    if (original) {
                        require(base.object("identity").node().equals(draftCall.input().object("context").node())
                                && base.string("identitySha256").equals(draftCall.input().string("contextSha256")), "base_draft_context");
                        StrictJson.Obj old = find(draftCall.input().objects("selected"), "issueId", issue.string("issueId"));
                        ObjectNode normalizedSelection = (ObjectNode) old.node().deepCopy(); normalizedSelection.put("rank", 1);
                        require(normalizedSelection.equals(selection.node()), "base_draft_selection");
                    } else {
                        envelope(layer, base, draftCall.input());
                        StrictJson.Obj supplied = find(draftCall.input().objects("selections"), "issueId", issue.string("issueId"));
                        require(supplied.node().equals(projectSelection(selection, true)), "generation_selection");
                        for (String id : draftCall.input().object("priorFailures").node().propertyNames())
                            require(draftCall.input().objects("selections").stream().anyMatch(s -> id.equals(s.string("issueId"))), "generation_foreign_failure");
                    }
                }
                boolean factPass = false; ArrayNode finalChecks = StrictJson.newArray();
                if (!issue.isNull("verificationRequestDigest")) {
                    require(draftCall != null, "verification_without_draft");
                    boolean original = "base".equals(issue.string("verificationOrigin"));
                    require(original || "recovery".equals(issue.string("verificationOrigin")), "verification_origin");
                    Recording verified = originCall(layer, baseReceipts, issue.string("verificationRequestDigest"), original, output, used);
                    if (original) {
                        require("SELECTED".equals(base.string("selectionStatus")) && "base".equals(issue.string("draftOrigin"))
                                && base.object("result").string("verificationRequestDigest").equals(issue.string("verificationRequestDigest"))
                                && base.object("result").string("generationRequestDigest").equals(issue.string("draftSourceRequestDigest")), "base_verification_reuse");
                        for (StrictJson.Obj check : base.object("result").object("verification").objects("checks"))
                            if (check.string("targetId").startsWith(issue.string("issueId") + ":")) finalChecks.add(check.node().deepCopy());
                        require(issue.object("verification").array("checks").equals(finalChecks)
                                && "PASS".equals(issue.object("verification").string("status")), "base_verification_exact");
                        factPass = true;
                    } else {
                        require((PREFIX + "verification").equals(verified.receipt().string("stage")), "verification_phase");
                        envelope(layer, base, verified.input());
                        StrictJson.Obj supplied = find(verified.input().objects("items"), "issueId", issue.string("issueId"));
                        require(supplied.object("draft").node().equals(issue.object("draft").node())
                                && supplied.array("sources").equals(projectSources(selection.array("sources"))), "verified_current_draft");
                        Map<String, String> targets = targets(issue.object("draft")); List<StrictJson.Obj> raw = rows(verified.answer().raw("checks"));
                        ArrayNode exactChecks = StrictJson.newArray(); factPass = true;
                        for (var target : targets.entrySet()) {
                            StrictJson.Obj check = find(raw, "targetId", target.getKey()); exactChecks.add(check.node().deepCopy());
                            boolean bound = target.getValue().equals(check.string("checkedText"));
                            String span = check.stringOrNull("unsupportedSpan");
                            boolean supported = "SUPPORTED".equals(check.string("verdict")) && bound && span == null;
                            ObjectNode projected = (ObjectNode) check.node().deepCopy(); projected.remove("flags");
                            for (String flag : FLAGS) { boolean value = check.object("flags").bool(flag); projected.put(flag, value); supported &= value; }
                            factPass &= supported; finalChecks.add(projected);
                        }
                        require(issue.object("verification").array("checks").equals(exactChecks)
                                && (factPass ? "PASS" : "WITHHELD").equals(issue.object("verification").string("status")), "verification_exact_result");
                    }
                }
                boolean novel = novelty(layer, base, issue, selection, history, used);
                if ("PASS".equals(issue.string("status"))) {
                    require(factPass && novel && draftCall != null && issue.array("errors").isEmpty(), "pass_proof_required");
                    validateDraft(issue.object("draft"), selection);
                    Set<String> issueDocuments = new HashSet<>(); selection.objects("sources").forEach(s -> issueDocuments.add(s.string("documentId")));
                    require(java.util.Collections.disjoint(sourceDocuments, issueDocuments), "published_source_overlap"); sourceDocuments.addAll(issueDocuments);
                    int rank = expectedSelected.size() + 1;
                    ObjectNode effectiveSelection = (ObjectNode) selection.node().deepCopy(); effectiveSelection.put("rank", rank); expectedSelected.add(effectiveSelection);
                    ObjectNode effectiveDraft = (ObjectNode) issue.object("draft").node().deepCopy(); effectiveDraft.put("rank", rank); expectedItems.add(effectiveDraft);
                    finalChecks.forEach(expectedChecks::add);
                    for (String key : List.of("draftSourceRequestDigest", "verificationRequestDigest", "noveltyRequestDigest"))
                        if (!issue.isNull(key)) expectedUsage.add(issue.string(key));
                } else require(!issue.array("errors").isEmpty(), "withheld_reason_required");
            }
            require(round.bool("partial") == (!expectedSelected.isEmpty() && issues.stream().anyMatch(i -> !"PASS".equals(i.string("status")))), "partial_binding");
            require(round.array("selected").equals(expectedSelected), "effective_selected");
            if (base.has("groupedSelectionRequestDigest") && !base.isNull("groupedSelectionRequestDigest")) {
                String key = base.string("groupedSelectionRequestDigest");
                Recording selection = recording(StrictJson.Obj.of(baseReceipts.get(key)), output, false, null);
                Set<String> originalIds = new HashSet<>(); selection.answer().objects("selected").forEach(i -> originalIds.add(i.string("issueId")));
                require(ids.equals(originalIds), "original_issue_population");
            } else require(ids.isEmpty(), "issues_without_original_selection");
            if (expectedSelected.isEmpty()) {
                require(!"SELECTED".equals(round.string("status")) && round.isNull("result") && round.isNull("resultSha256"), "empty_round_held");
            } else {
                require("SELECTED".equals(round.string("status")), "published_status");
                StrictJson.Obj result = round.object("result"); Instant.parse(result.string("generatedAt"));
                require(result.array("items").equals(expectedItems) && "PASS".equals(result.object("verification").string("status"))
                        && result.object("verification").array("checks").equals(expectedChecks)
                        && Canonical.digest(result.node()).equals(round.string("resultSha256")), "effective_result");
                Set<String> actualUsage = new HashSet<>();
                for (StrictJson.Obj receipt : result.objects("usage")) {
                    String digest = receipt.string("requestDigest");
                    require(actualUsage.add(digest) && receipt.node().equals(layer.receipts().getOrDefault(digest, baseReceipts.get(digest))), "effective_usage");
                }
                require(actualUsage.equals(expectedUsage), "effective_usage_coverage");
                for (JsonNode selected : expectedSelected) {
                    ObjectNode prior = history.addObject().put("issueId", selected.path("issueId").stringValue());
                    prior.set("sources", selected.path("sources").deepCopy());
                }
            }
        }
        require(appliedEditorial.equals(editorial.keySet()), "unknown_editorial_hold");
        // Failed or superseded attempts retain their raw recordings without authorizing the final draft.
        // Bind their restricted context and source projection as well, even if a later repair superseded them.
        for (Recording call : layer.recordings().values()) {
            StrictJson.Obj base = bundle.objects("rounds").stream().filter(r -> r.string("date").equals(call.input().object("context").string("date"))
                    && r.string("edition").equals(call.input().object("context").string("edition"))).findFirst().orElseThrow();
            envelope(layer, base, call.input());
            StrictJson.Obj effective = layer.rounds().get(base.string("roundId"));
            String phase = call.receipt().string("stage").substring(PREFIX.length());
            String field = "verification".equals(phase) ? "items" : "selections";
            for (StrictJson.Obj item : call.input().objects(field)) {
                StrictJson.Obj issue = find(effective.objects("issues"), "issueId", item.string("issueId"));
                require(!issue.isNull("selection"), "attempt_selection_missing");
                if ("verification".equals(phase)) require(item.array("sources").equals(projectSources(issue.object("selection").array("sources"))), "attempt_verification_source");
                else require(item.node().equals(projectSelection(issue.object("selection"), "generation".equals(phase))), "attempt_selection_source");
            }
        }
    }

    private static StrictJson.Obj sourceSelection(StrictJson.Obj base, StrictJson.Obj issue, Map<String, JsonNode> receipts, Path output) {
        String digest = issue.string("sourceSelectionRequestDigest");
        require(digest.equals(base.string("groupedSelectionRequestDigest")) && receipts.containsKey(digest), "selection_origin");
        Recording call = recording(StrictJson.Obj.of(receipts.get(digest)), output, false, null);
        require("grouped_issue_selection".equals(call.receipt().string("stage")), "selection_stage");
        List<StrictJson.Obj> choices = new ArrayList<>(call.answer().objects("selected"));
        choices.sort(java.util.Comparator.comparingInt((StrictJson.Obj c) -> -call.answer().object("assessments").object(c.string("issueId")).count("importance"))
                .thenComparingInt(c -> -call.answer().object("assessments").object(c.string("issueId")).count("priority"))
                .thenComparing(c -> c.string("issueId")));
        StrictJson.Obj choice = find(choices, "issueId", issue.string("issueId"));
        require(issue.count("originalRank") == choices.indexOf(choice) + 1, "original_rank");
        StrictJson.Obj candidate = find(call.input().objects("issues"), "issueId", issue.string("issueId"));
        StrictJson.Obj assessment = call.answer().object("assessments").object(issue.string("issueId"));
        require("SELECTABLE".equals(assessment.string("status")) && assessment.count("importance") >= 2, "selection_eligible");
        if (assessment.count("importance") == 3) require(Set.of("BROAD_MARKET", "COMMON_POLICY").contains(assessment.string("scope"))
                && !assessment.string("transmission").isBlank() && (!"BROAD_MARKET".equals(assessment.string("scope"))
                || Set.copyOf(assessment.strings("affectedSectors")).size() >= 2), "selection_broad_proof");
        StrictJson.Obj selected = issue.object("selection");
        selected.exactly(Set.of("issueId", "rank", "eventKey", "title", "reason", "companyNames", "companyLinks", "score", "importance", "scope",
                "affectedSectors", "transmission", "limitations", "sources", "selectionInputSha256", "quoteBindingPolicy", "groupingMeaning",
                "groupedIssueSnapshotSha256", "frozenGroupedIssueSnapshot", "novelty"));
        require(selected.string("issueId").equals(issue.string("issueId")) && selected.count("rank") == 1
                && selected.string("eventKey").equals(issue.string("issueId"))
                && selected.object("frozenGroupedIssueSnapshot").node().equals(candidate.node())
                && selected.string("groupedIssueSnapshotSha256").equals(candidate.string("asOfSnapshotSha256"))
                && selected.string("selectionInputSha256").equals(base.string("identitySha256")), "selection_snapshot");
        for (String key : List.of("title", "limitations")) require(selected.raw(key).equals(choice.raw(key)), "selection_choice");
        for (String key : List.of("reason", "importance", "scope", "affectedSectors", "transmission")) require(selected.raw(key).equals(assessment.raw(key)), "selection_assessment");
        require(selected.count("score") == assessment.count("priority"), "selection_priority");
        require("accepted_grouped_issue_exact_span_v1".equals(selected.string("quoteBindingPolicy"))
                && "Reused accepted issue archive identity; not an operating graph/publication approval.".equals(selected.string("groupingMeaning"))
                && selected.objects("novelty").size() == 1 && selected.objects("novelty").getFirst().string("decision").equals(choice.string("novelty"))
                && selected.objects("novelty").getFirst().array("deltaEvidenceIds").equals(choice.array("deltaEvidenceIds")), "selection_novelty_origin");
        Map<String, JsonNode> evidence = new LinkedHashMap<>(), company = new LinkedHashMap<>(); Map<String, Set<String>> companyRefs = new LinkedHashMap<>();
        for (String field : List.of("backgroundMentions", "newMentions")) for (StrictJson.Obj mention : candidate.objects(field)) {
            if ("newMentions".equals(field)) for (StrictJson.Obj source : mention.objects("evidence")) evidence.put(source.string("evidenceId"), source.node());
            for (StrictJson.Obj link : mention.objects("companies")) {
                JsonNode old = company.putIfAbsent(link.string("companyId"), link.node());
                require(old == null || old.path("name").equals(link.raw("name")), "company_identity");
                companyRefs.computeIfAbsent(link.string("companyId"), ignored -> new HashSet<>()).addAll(link.strings("evidenceIds"));
            }
        }
        List<String> ids = choice.strings("evidenceIds"); require(!ids.isEmpty() && Set.copyOf(ids).size() == ids.size(), "selection_evidence_ids");
        require(selected.objects("sources").size() == ids.size(), "selection_sources");
        for (int i = 0; i < ids.size(); i++) require(selected.objects("sources").get(i).node().equals(evidence.get(ids.get(i))), "selection_exact_source");
        List<StrictJson.Obj> links = selected.objects("companyLinks"); List<String> companyIds = choice.strings("companyIds");
        require(links.size() == companyIds.size() && selected.strings("companyNames").equals(links.stream().map(l -> l.string("name")).toList()), "selection_companies");
        for (int i = 0; i < links.size(); i++) {
            StrictJson.Obj link = links.get(i); JsonNode known = company.get(companyIds.get(i));
            require(known != null && companyIds.get(i).equals(link.string("companyId")) && known.path("name").equals(link.raw("name"))
                    && known.path("role").equals(link.raw("role")), "selection_company_link");
            Set<String> refs = new HashSet<>(companyRefs.get(companyIds.get(i))); refs.retainAll(ids);
            require(!refs.isEmpty() && refs.equals(Set.copyOf(link.strings("evidenceIds"))), "selection_company_evidence");
        }
        return selected;
    }

    private static boolean novelty(Layer layer, StrictJson.Obj base, StrictJson.Obj issue, StrictJson.Obj selection, ArrayNode history, Set<String> used) {
        if (issue.isNull("noveltyDecision")) { require(issue.isNull("noveltyRequestDigest"), "novelty_without_decision"); return false; }
        StrictJson.Obj decision = issue.object("noveltyDecision");
        require(issue.string("issueId").equals(decision.string("issueId")), "novelty_issue");
        if (issue.isNull("noveltyRequestDigest")) require(history.isEmpty() && "NEW".equals(decision.string("decision"))
                && decision.strings("deltaEvidenceIds").isEmpty(), "novelty_server_empty_history");
        else {
            Recording call = layer.recordings().get(issue.string("noveltyRequestDigest"));
            require(call != null && (PREFIX + "novelty").equals(call.receipt().string("stage")), "novelty_phase"); used.add(issue.string("noveltyRequestDigest"));
            envelope(layer, base, call.input());
            StrictJson.Obj supplied = find(call.input().objects("selections"), "issueId", issue.string("issueId"));
            require(supplied.node().equals(projectSelection(selection, false)), "novelty_selection");
            ArrayNode safeHistory = StrictJson.newArray();
            for (JsonNode prior : history) safeHistory.add(projectSelection(StrictJson.Obj.of(prior), false));
            require(call.input().array("history").equals(safeHistory) && !safeHistory.isEmpty(), "novelty_history");
            require(find(rows(call.answer().raw("decisions")), "issueId", issue.string("issueId")).node().equals(decision.node()), "novelty_exact_response");
        }
        require(Set.of("NEW", "MATERIAL_UPDATE", "REPEAT", "UNCERTAIN").contains(decision.string("decision")) && !decision.string("reason").isBlank(), "novelty_decision");
        Set<String> delta = Set.copyOf(decision.strings("deltaEvidenceIds"));
        Map<String, String> sources = new LinkedHashMap<>(); selection.objects("sources").forEach(s -> sources.put(s.string("evidenceId"), s.string("quote")));
        if (delta.size() != decision.strings("deltaEvidenceIds").size() || !sources.keySet().containsAll(delta)) return false;
        if ("MATERIAL_UPDATE".equals(decision.string("decision"))) {
            Set<String> old = new HashSet<>(); for (JsonNode row : history) StrictJson.Obj.of(row).objects("sources").forEach(s -> old.add(s.string("quote")));
            return !delta.isEmpty() && delta.stream().anyMatch(d -> !old.contains(sources.get(d)));
        }
        return "NEW".equals(decision.string("decision"));
    }

    private static void validateDraft(StrictJson.Obj draft, StrictJson.Obj selection) {
        draft.exactly(Set.of("issueId", "rank", "title", "titleEvidenceIds", "claims"));
        require(draft.count("rank") == 1 && draft.string("issueId").equals(selection.string("issueId"))
                && !draft.string("title").isBlank() && !draft.objects("claims").isEmpty() && draft.objects("claims").size() <= 3, "draft_shape");
        Set<String> ids = new HashSet<>(); selection.objects("sources").forEach(s -> ids.add(s.string("evidenceId")));
        cite(draft.strings("titleEvidenceIds"), ids);
        validateText(draft.string("title"), 80, draft.strings("titleEvidenceIds"), selection);
        for (StrictJson.Obj claim : draft.objects("claims")) {
            claim.exactly(Set.of("text", "type", "evidenceIds"));
            require(Set.of("fact", "plan", "outlook").contains(claim.string("type")) && !claim.string("text").isBlank(), "draft_claim");
            cite(claim.strings("evidenceIds"), ids);
            validateText(claim.string("text"), 250, claim.strings("evidenceIds"), selection);
        }
    }
    private static void validateText(String text, int max, List<String> ids, StrictJson.Obj selection) {
        require(text.codePointCount(0, text.length()) <= max && !text.contains("\n")
                && !Pattern.compile("(?:다[.!?]|요[.!?]|[。！？])\\s+\\S").matcher(text).find()
                && !Pattern.compile("매수|매도|목표가|수익.{0,3}보장|오늘|내일|금일|종가|장\\s*마감|환율\\s*마감").matcher(text).find(), "draft_atomic_safe_text");
        List<String> quotes = selection.objects("sources").stream().filter(s -> ids.contains(s.string("evidenceId"))).map(s -> s.string("quote")).toList();
        validateKrwAmounts(text, quotes);
    }

    /** Exact, explicitly denominated KRW only; ranges and unsupported chained units remain unclassified. */
    static void validateKrwAmounts(String text, List<String> quotes) {
        Set<BigDecimal> source = new HashSet<>(); quotes.forEach(q -> source.addAll(krwAmounts(q)));
        Set<BigDecimal> stated = krwAmounts(text);
        if (!source.isEmpty()) require(source.containsAll(stated), "draft_krw_scale_mismatch");
    }
    private static Set<BigDecimal> krwAmounts(String text) {
        Set<BigDecimal> result = new HashSet<>();
        String number = "(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\\.[0-9]+)?";
        if (Pattern.compile("~|～|–|\\bbetween\\b|\\bfrom\\s+" + number + "|" + number + "\\s*(?:-|\\bto\\b)\\s*" + number,
                Pattern.CASE_INSENSITIVE).matcher(text).find()) return result;
        var english = Pattern.compile("(?<![\\p{L}\\d.,])(" + number + ")\\s*(trillion|billion|million|thousand)\\s*(?:South\\s+Korean\\s+|Korean\\s+)?(?:won|KRW)(?![\\p{L}\\d])", Pattern.CASE_INSENSITIVE).matcher(text);
        while (english.find()) {
            int power = switch (english.group(2).toLowerCase(java.util.Locale.ROOT)) { case "trillion" -> 12; case "billion" -> 9; case "million" -> 6; default -> 3; };
            result.add(new BigDecimal(english.group(1).replace(",", "")).scaleByPowerOfTen(power).stripTrailingZeros());
        }
        var korean = Pattern.compile("(?<![\\p{L}\\d.,])((?:" + number + "\\s*[조억만천]\\s*)+|" + number + ")\\s*원").matcher(text);
        while (korean.find()) {
            String amount = korean.group(1); var parts = Pattern.compile("(" + number + ")\\s*([조억만천]?)").matcher(amount);
            BigDecimal value = BigDecimal.ZERO; int previous = Integer.MAX_VALUE; boolean recognized = true;
            while (parts.find()) {
                int power = switch (parts.group(2)) { case "조" -> 12; case "억" -> 8; case "만" -> 4; case "천" -> 3; default -> 0; };
                if (power >= previous) recognized = false; previous = power;
                value = value.add(new BigDecimal(parts.group(1).replace(",", "")).scaleByPowerOfTen(power));
            }
            if (recognized) result.add(value.stripTrailingZeros());
        }
        return result;
    }
    private static void cite(List<String> values, Set<String> allowed) { require(!values.isEmpty() && Set.copyOf(values).size() == values.size() && allowed.containsAll(values), "draft_citation"); }
    private static Map<String, String> targets(StrictJson.Obj draft) {
        Map<String, String> result = new LinkedHashMap<>(); String id = draft.string("issueId"); result.put(id + ":title", draft.string("title"));
        for (int i = 0; i < draft.objects("claims").size(); i++) result.put(id + ":claim:" + i, draft.objects("claims").get(i).string("text")); return result;
    }
    private static JsonNode projectSelection(StrictJson.Obj selection, boolean companies) {
        ObjectNode value = StrictJson.newObject().put("issueId", selection.string("issueId"));
        if (companies) value.put("rank", 1);
        value.set("sources", projectSources(selection.array("sources")));
        if (companies) value.set("companyLinks", selection.array("companyLinks").deepCopy()); return value;
    }
    private static ArrayNode projectSources(JsonNode sources) {
        ArrayNode result = StrictJson.newArray();
        for (JsonNode raw : sources) {
            StrictJson.Obj source = StrictJson.Obj.of(raw); ObjectNode value = StrictJson.newObject();
            for (String key : List.of("evidenceId", "documentId", "documentVersion", "bodySha256", "quote", "start", "end")) value.set(key, source.raw(key).deepCopy());
            value.put("offsetUnit", "unicode_code_point");
            if (source.has("publicationClock")) value.put("publishedAt", source.object("publicationClock").string("publishedAt"));
            else value.put("publishedAt", source.string("publishedAt"));
            if (source.has("clockRecordSha256")) value.put("clockRecordSha256", source.string("clockRecordSha256")); result.add(value);
        }
        return result;
    }
    private static void envelope(Layer layer, StrictJson.Obj base, StrictJson.Obj input) {
        require(SCHEMA.equals(input.string("schemaVersion")) && input.object("promptArtifacts").node().equals(layer.root().object("promptArtifacts").node()), "request_envelope");
        StrictJson.Obj context = input.object("context");
        require(base.string("date").equals(context.string("date")) && base.string("edition").equals(context.string("edition"))
                && base.object("window").node().equals(context.object("window").node())
                && "publication_clock_simulation".equals(context.string("mode")) && !context.bool("operationalCollectionGate")
                && !context.bool("historicalBodyUnchangedProven"), "request_context");
        for (String key : List.of("roundId", "sourceFileSha256", "groupArchiveSha256", "contextSha256")) if (context.has(key)) {
            String expected = "contextSha256".equals(key) ? base.string("identitySha256") : "roundId".equals(key) ? base.string("roundId") : base.object("identity").string(key);
            require(expected.equals(context.string(key)), "request_context_identity");
        }
        for (String key : List.of("policyVersion", "baseBundleSha256", "clockFileSha256")) if (context.has(key))
            require(layer.root().string(key).equals(context.string(key)), "request_layer_identity");
        if (context.has("recoveryRunId")) require(layer.root().string("runId").equals(context.string("recoveryRunId")), "request_run_identity");
        context.keys(Set.of("date", "edition", "window", "mode", "historicalBodyUnchangedProven", "operationalCollectionGate"),
                Set.of("roundId", "sourceFileSha256", "groupArchiveSha256", "contextSha256", "recoveryRunId", "policyVersion", "baseBundleSha256", "clockFileSha256"));
    }
    private static Recording originCall(Layer layer, Map<String, JsonNode> base, String digest, boolean original, Path output, Set<String> used) {
        if (original) { require(base.containsKey(digest), "base_receipt_required"); return recording(StrictJson.Obj.of(base.get(digest)), output, false, null); }
        Recording call = layer.recordings().get(digest); require(call != null && call.answer() != null, "recovery_receipt_required"); used.add(digest); return call;
    }
    private static Recording recording(StrictJson.Obj receipt, Path output, boolean recovery, StrictJson.Obj prompts) {
        String digest = receipt.string("requestDigest"); require(digest.matches("[0-9a-f]{64}"), "request_digest_format");
        byte[] bytes = read(output.resolve("calls").resolve(digest + ".request.json")); StrictJson.Obj request = StrictJson.parseObject(bytes);
        require(digest.equals(Canonical.sha256(bytes)) && !request.bool("store") && receipt.string("model").equals(request.string("model"))
                && receipt.string("stage").equals(request.object("text").object("format").string("name")), "request_recording");
        StrictJson.Obj input = StrictJson.parseObject(request.string("input"));
        if (recovery) {
            String phase = receipt.string("stage").substring(PREFIX.length());
            require(Canonical.sha256(request.string("instructions")).equals(prompts.string(phase + ".md"))
                    && input.object("promptArtifacts").node().equals(prompts.node()), "request_prompt");
            Set<String> keys = new HashSet<>(Set.of("schemaVersion", "context", "promptArtifacts"));
            keys.add("verification".equals(phase) ? "items" : "selections");
            if ("generation".equals(phase)) keys.add("priorFailures");
            if ("novelty".equals(phase)) keys.add("history");
            input.exactly(keys);
            if ("verification".equals(phase)) for (StrictJson.Obj item : input.objects("items"))
                item.exactly(Set.of("issueId", "draft", "sources"));
            if ("generation".equals(phase)) for (String key : input.object("priorFailures").node().propertyNames())
                for (String code : input.object("priorFailures").strings(key)) require(code.matches("[A-Za-z0-9_.:-]{1,160}"), "machine_failure_code_only");
            require(request.object("text").object("format").object("schema").node().equals(schema(phase, input)), "request_schema");
        } else {
            String stage = receipt.string("stage"), prompt = "grouped_issue_selection".equals(stage) ? "grouped-selection.md"
                    : stage.endsWith("_verification") ? "grouped-verification.md" : "grouped-generation-" + input.string("edition") + ".md";
            require(Canonical.sha256(request.string("instructions")).equals(input.object("context").object("promptArtifacts").string(prompt)), "base_request_prompt");
        }
        byte[] raw = read(output.resolve("calls").resolve(digest + ".response.json")); StrictJson.Obj response = StrictJson.parseObject(raw);
        require(Canonical.sha256(raw).equals(receipt.string("responseSha256")) && receipt.bool("usageKnown") && receipt.count("httpStatus") == 200
                && "completed".equals(receipt.string("status")) && response.string("status").equals(receipt.string("status"))
                && response.string("id").equals(receipt.string("responseId"))
                && response.object("usage").count("input_tokens") == receipt.count("inputTokens")
                && response.object("usage").count("output_tokens") == receipt.count("outputTokens"), "response_recording");
        List<String> texts = new ArrayList<>(); for (StrictJson.Obj item : response.objects("output")) if ("message".equals(item.string("type")))
            for (StrictJson.Obj content : item.objects("content")) if ("output_text".equals(content.string("type"))) texts.add(content.string("text"));
        require(texts.size() == 1, "single_response_text"); StrictJson.Obj answer = StrictJson.parseObject(texts.getFirst());
        if (recovery) {
            String phase = receipt.string("stage").substring(PREFIX.length());
            String field = "generation".equals(phase) ? "items" : "verification".equals(phase) ? "checks" : "decisions";
            String idField = "verification".equals(phase) ? "targetId" : "issueId";
            Set<String> expected = new HashSet<>();
            if ("verification".equals(phase)) input.objects("items").forEach(i -> expected.addAll(targets(i.object("draft")).keySet()));
            else input.objects("selections").forEach(i -> require(expected.add(i.string("issueId")), "request_duplicate_issue"));
            Set<String> actual = new HashSet<>();
            for (StrictJson.Obj row : rows(answer.raw(field))) require(actual.add(row.string(idField)), "response_duplicate_target");
            require(actual.equals(expected), "response_full_coverage");
            if (answer.raw(field).isObject()) for (String key : answer.object(field).node().propertyNames())
                require(key.equals(answer.object(field).object(key).string(idField)), "response_key_identity");
        }
        return new Recording(input, answer, receipt);
    }
    private static JsonNode schema(String phase, StrictJson.Obj input) {
        ObjectNode schema = (ObjectNode) StrictJson.parseObject(resource(phase + ".schema.json")).node().deepCopy();
        String field = "generation".equals(phase) ? "items" : "verification".equals(phase) ? "checks" : "decisions";
        JsonNode template = schema.path("properties").path(field).path("items"); ObjectNode properties = StrictJson.newObject();
        List<String> keys = new ArrayList<>();
        if ("verification".equals(phase)) input.objects("items").forEach(i -> keys.addAll(targets(i.object("draft")).keySet()));
        else input.objects("selections").forEach(i -> keys.add(i.string("issueId")));
        for (String key : keys) {
            ObjectNode item = (ObjectNode) template.deepCopy(); String idField = "verification".equals(phase) ? "targetId" : "issueId";
            ((ObjectNode) item.path("properties").path(idField)).putArray("enum").add(key);
            if ("generation".equals(phase)) {
                StrictJson.Obj selection = find(input.objects("selections"), "issueId", key);
                ArrayNode titles = ((ObjectNode) item.path("properties").path("titleEvidenceIds").path("items")).putArray("enum");
                ArrayNode claims = ((ObjectNode) item.path("properties").path("claims").path("items").path("properties").path("evidenceIds").path("items")).putArray("enum");
                selection.objects("sources").forEach(s -> { titles.add(s.string("evidenceId")); claims.add(s.string("evidenceId")); });
            }
            properties.set(key, item);
        }
        ObjectNode keyed = StrictJson.newObject().put("type", "object").put("additionalProperties", false);
        keyed.set("properties", properties); ArrayNode required = keyed.putArray("required"); keys.forEach(required::add);
        ((ObjectNode) schema.path("properties")).set(field, keyed); return schema;
    }
    private static List<StrictJson.Obj> rows(JsonNode value) {
        List<StrictJson.Obj> rows = new ArrayList<>();
        if (value.isArray()) value.forEach(v -> rows.add(StrictJson.Obj.of(v)));
        else { require(value.isObject(), "response_rows"); value.propertyNames().forEach(k -> rows.add(StrictJson.Obj.of(value.get(k)))); }
        return rows;
    }
    private static StrictJson.Obj find(List<StrictJson.Obj> values, String field, String id) {
        List<StrictJson.Obj> matches = values.stream().filter(v -> id.equals(v.string(field))).toList(); require(matches.size() == 1, "response_identity_coverage"); return matches.getFirst();
    }
    private static byte[] resource(String name) {
        try (var stream = BriefingGroupedRecoveryRules.class.getResourceAsStream("/briefing/prompts/item-recovery/" + name)) {
            require(stream != null, "prompt_resource"); return stream.readAllBytes();
        } catch (IOException error) { throw new IllegalArgumentException("Recovery prompt unavailable", error); }
    }
    private static byte[] read(Path path) {
        try { require(Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS) && path.getParent().equals(path.getParent().toRealPath())
                    && Files.size(path) <= 128 * 1024 * 1024, "artifact_file"); return Files.readAllBytes(path); }
        catch (IOException error) { throw new IllegalArgumentException("Recovery artifact unavailable", error); }
    }
    private static void require(boolean valid, String code) { if (!valid) throw new IllegalArgumentException("Grouped recovery rejected: " + code); }
}
