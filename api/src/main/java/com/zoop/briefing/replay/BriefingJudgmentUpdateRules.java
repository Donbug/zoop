package com.zoop.briefing.replay;

import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.time.LocalDate;
import java.util.*;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ObjectNode;
import static com.zoop.briefing.replay.BriefingCompanySchemas.*;

/** Industry interpretation is separate from same-company historical judgments and selection membership. */
public final class BriefingJudgmentUpdateRules {
    static final String SCHEMA = "zoop-judgment-update-v1";
    static final List<String> QUALITY = List.of("factsSupported", "materialConditionsPreserved", "previousJudgmentFaithful", "interpretationBounded", "cardsMatchConclusion");
    static final List<String> FIELDS = List.of("newEvidence", "reason", "strengthenIf", "weakenIf", "topic", "title", "description");
    private BriefingJudgmentUpdateRules() { }

    static ObjectNode format(String phase, StrictJson.Obj frozen) {
        ObjectNode fields = StrictJson.newObject();
        if ("verification".equals(phase)) {
            QUALITY.forEach(k -> fields.set(k, StrictJson.newObject().put("type", "boolean")));
            fields.set("reason", text(1600));
        } else {
            List<String> ids = new ArrayList<>(frozen.object("sources").node().propertyNames()); Collections.sort(ids);
            ObjectNode c = StrictJson.newObject();
            c.set("companyId", choice(frozen.objects("targets").stream().map(t -> t.string("companyId")).toList()));
            c.set("decision", choice(List.of("initial", "maintained", "strengthened", "weakened", "unassessable")));
            for (String k : FIELDS) c.set(k, statement(ids, maximum(k)));
            fields.set("conclusion", statement(ids, 420)); fields.set("industryChange", statement(ids, 700));
            fields.set("companies", array(object(c), frozen.objects("targets").size(), frozen.objects("targets").size()));
            fields.set("limits", statement(ids, 500));
        }
        ObjectNode format = StrictJson.newObject().put("type", "json_schema").put("name", "judgment_update_" + phase).put("strict", true);
        format.set("schema", object(fields)); return format;
    }
    private static int maximum(String field) {
        return switch (field) { case "topic" -> 12; case "title" -> 32; case "description" -> 64;
            case "strengthenIf", "weakenIf" -> 240; default -> 500; };
    }
    static ObjectNode freeze(StrictJson.Obj current, StrictJson.Obj previous, Map<String, BriefingPresentationRules.Evidence> evidence) {
        require("PASS".equals(current.string("status")) && "PASS".equals(previous.string("status")), "pass_inputs");
        require(Instant.parse(previous.string("cutoff")).isBefore(Instant.parse(current.string("cutoff"))), "previous_clock");
        boolean evening = "evening".equals(current.string("edition"));
        require(evening ? "morning".equals(previous.string("edition")) && previous.string("date").equals(current.string("date"))
                : "evening".equals(previous.string("edition")) && LocalDate.parse(previous.string("date")).equals(LocalDate.parse(current.string("date")).minusDays(1)), "previous_edition");
        ObjectNode f = StrictJson.newObject().put("schemaVersion", SCHEMA);
        for (String k : List.of("roundId", "date", "edition", "cutoff")) f.put(k, current.string(k));
        f.put("companyResultVersion", current.string("resultVersion")).put("previousRoundId", previous.string("roundId"))
                .put("previousResultVersion", previous.string("resultVersion")).put("previousCutoff", previous.string("cutoff"));
        f.set("previousDraft", previous.raw("draft").deepCopy());
        Map<String, ObjectNode> targets = new LinkedHashMap<>(); ObjectNode sources = StrictJson.newObject();
        for (StrictJson.Obj row : List.of(current, previous)) for (StrictJson.Obj t : row.object("frozen").objects("targets")) {
            String cid = t.string("companyId");
            ObjectNode target = targets.computeIfAbsent(cid, id -> {
                ObjectNode value = StrictJson.newObject().put("companyId", cid).put("companyName", t.string("companyName"))
                        .put("role", row == current ? "selected" : "watch");
                value.putArray("sourceIds");
                var old = previous.object("draft").objects("companies").stream().filter(c -> c.string("companyId").equals(cid)).findFirst();
                if (old.isPresent()) { value.set("previousJudgment", old.get().node().deepCopy()); value.put("previousResultVersion", previous.string("resultVersion")); }
                else { value.putNull("previousJudgment"); value.putNull("previousResultVersion"); }
                return value;
            });
            for (String sid : t.strings("sourceIds")) {
                var actual = evidence.get(sid); require(actual != null, "source_missing");
                StrictJson.Obj saved = row.object("frozen").object("sources").object(sid);
                require(actual.bodySha256().equals(saved.string("bodySha256")) && Canonical.sha256(actual.body().getBytes(java.nio.charset.StandardCharsets.UTF_8)).equals(actual.bodySha256())
                        && actual.documentId().equals(saved.string("documentId")) && actual.body().contains(saved.string("quote"))
                        && !Instant.parse(saved.string("publishedAt")).isAfter(Instant.parse(current.string("cutoff")))
                        && actual.body().codePointCount(0, actual.body().length()) <= 24000, "source_identity");
                ObjectNode s = (ObjectNode) saved.node().deepCopy(); s.put("fullBody", actual.body());
                require(!sources.has(sid) || sources.get(sid).equals(s), "source_conflict"); sources.set(sid, s);
                if (!StrictJson.Obj.of(target).strings("sourceIds").contains(sid)) ((tools.jackson.databind.node.ArrayNode) target.path("sourceIds")).add(sid);
            }
        }
        require(!targets.isEmpty() && targets.size() <= 6, "target_count");
        var list = f.putArray("targets"); targets.values().forEach(list::add); f.set("sources", sources);
        f.put("scopeNote", "원발행 시각 기준 과거 시뮬레이션입니다. 늦게 수집한 보존 원문을 사용하며 당시 본문 동일성은 입증하지 않습니다. 산업 해석과 같은 기업의 이전 판단을 구분합니다.");
        return f;
    }
    static ObjectNode apply(StrictJson.Obj row, StrictJson.Obj current, StrictJson.Obj previous,
            Map<String, BriefingPresentationRules.Evidence> evidence, Map<String, JsonNode> receipts,
            Path output, Set<String> owned) {
        StrictJson.Obj frozen = row.object("frozen");
        require(freeze(current, previous, evidence).equals(frozen.node()) && current.string("roundId").equals(row.string("roundId")), "frozen_binding");
        ObjectNode version = (ObjectNode) row.node().deepCopy(); version.remove("resultVersion");
        require(("judgment-v1-" + Canonical.digest(version)).equals(row.string("resultVersion")), "version");
        List<StrictJson.Obj> attempts = row.objects("attempts"); require(attempts.size() == 1, "attempt_count");
        StrictJson.Obj attempt = attempts.getFirst();
        for (String phase : List.of("generation", "verification")) {
            String key = phase + "RequestDigest"; if (!attempt.has(key)) continue;
            StrictJson.Obj actual = BriefingCompanyOutlookRules.recordedCall(attempt.string(key), phase, frozen, receipts, output, owned, "judgment_update_", "judgment-update-v1");
            require(actual.node().equals(attempt.object(phase.equals("generation") ? "draft" : "verification").node()), "recorded_response");
            require(!Instant.parse(StrictJson.Obj.of(receipts.get(attempt.string(key))).string("finishedAt")).isAfter(Instant.parse(row.string("generatedAt"))), "completion_clock");
            if (phase.equals("verification")) try {
                StrictJson.Obj request = StrictJson.parseObject(Files.readAllBytes(output.resolve("calls/" + attempt.string(key) + ".request.json")));
                require(StrictJson.parseObject(request.string("input")).object("draft").node().equals(attempt.object("draft").node()), "verification_binding");
            } catch (java.io.IOException e) { throw new IllegalArgumentException("Judgment recording missing", e); }
        }
        boolean passed = "PASS".equals(row.string("status")); require(passed || "WITHHELD".equals(row.string("status")), "status");
        ObjectNode out = StrictJson.newObject().put("schemaVersion", SCHEMA).put("status", row.string("status"));
        for (String k : List.of("roundId", "edition", "cutoff", "previousRoundId", "previousCutoff", "companyResultVersion", "previousResultVersion", "scopeNote")) out.put(k, frozen.string(k));
        out.put("resultVersion", row.string("resultVersion")).put("generatedAt", row.string("generatedAt"));
        if (passed) {
            require(row.object("draft").node().equals(attempt.object("draft").node()), "final_attempt");
            for (String key : QUALITY) require(attempt.object("verification").bool(key), "semantic_" + key);
            validateDraft(row.object("draft"), frozen);
            for (String key : List.of("conclusion", "industryChange", "limits", "companies")) out.set(key, row.object("draft").raw(key).deepCopy());
            Map<String, StrictJson.Obj> ts = new HashMap<>(); frozen.objects("targets").forEach(t -> ts.put(t.string("companyId"), t));
            for (JsonNode node : out.path("companies")) {
                ObjectNode c = (ObjectNode) node; StrictJson.Obj target = ts.get(c.path("companyId").stringValue());
                c.put("companyName", target.string("companyName")).put("role", target.string("role"));
                c.set("sourceIds", target.raw("sourceIds").deepCopy());
                c.set("previousJudgment", target.raw("previousJudgment").deepCopy()); c.set("previousResultVersion", target.raw("previousResultVersion").deepCopy());
            }
            out.set("sources", frozen.raw("sources").deepCopy());
            if (row.has("editorialReview")) {
                StrictJson.Obj edit = row.object("editorialReview");
                require("codex".equals(edit.string("reviewer")) && "pre_edit_draft".equals(edit.string("modelVerificationAppliesTo"))
                        && Canonical.digest(frozen.node()).equals(edit.string("frozenSha256")), "editorial_identity");
                require(!Instant.parse(edit.string("reviewedAt")).isBefore(Instant.parse(row.string("generatedAt"))) && !edit.string("reason").isBlank(), "editorial_clock");
                Set<String> changed = new HashSet<>();
                for (StrictJson.Obj change : edit.objects("changes")) {
                    String field = change.string("field"), cid = change.isNull("companyId") ? null : change.string("companyId");
                    require(changed.add(cid + "/" + field), "editorial_duplicate");
                    ObjectNode target;
                    if (cid == null) { require(Set.of("conclusion", "industryChange", "limits").contains(field), "editorial_scope"); target = out; }
                    else { require(FIELDS.contains(field), "editorial_scope"); target = (ObjectNode) out.path("companies").valueStream().filter(n -> cid.equals(n.path("companyId").stringValue())).findFirst().orElseThrow(); }
                    require(target.path(field).equals(change.raw("before")), "editorial_before");
                    target.set(field, change.raw("after").deepCopy());
                }
                validateDraft(StrictJson.Obj.of(out), frozen);
                out.set("editorialReview", edit.node().deepCopy());
            }
        } else { require(row.isNull("draft"), "withheld_draft"); out.put("reason", "비교 판단의 근거·조건 검증을 통과하지 못했습니다."); }
        return out;
    }
    static void validateDraft(StrictJson.Obj draft, StrictJson.Obj frozen) {
        Set<String> all = Set.copyOf(frozen.object("sources").node().propertyNames());
        for (String key : List.of("conclusion", "industryChange", "limits")) statementValue(draft.object(key), all, key.equals("industryChange") ? 700 : key.equals("conclusion") ? 420 : 500);
        Map<String, StrictJson.Obj> expected = new HashMap<>(); frozen.objects("targets").forEach(t -> expected.put(t.string("companyId"), t)); Set<String> seen = new HashSet<>();
        for (StrictJson.Obj c : draft.objects("companies")) {
            String id = c.string("companyId"); require(expected.containsKey(id) && seen.add(id), "company_coverage");
            StrictJson.Obj t = expected.get(id); String decision = c.string("decision");
            require(Set.of("initial", "maintained", "strengthened", "weakened", "unassessable").contains(decision), "decision");
            if (t.isNull("previousJudgment")) require(Set.of("initial", "unassessable").contains(decision), "invented_previous");
            if ("watch".equals(t.string("role"))) require(Set.of("maintained", "unassessable").contains(decision), "watch_without_update");
            for (String k : FIELDS) statementValue(c.object(k), Set.copyOf(t.strings("sourceIds")), maximum(k));
        }
        require(seen.equals(expected.keySet()), "company_coverage");
    }
    public static void validateProjection(JsonNode node, String round, String edition, Instant cutoff) {
        StrictJson.Obj value = StrictJson.Obj.of(node);
        require(SCHEMA.equals(value.string("schemaVersion")) && round.equals(value.string("roundId")) && edition.equals(value.string("edition"))
                && cutoff.equals(Instant.parse(value.string("cutoff"))) && Instant.parse(value.string("previousCutoff")).isBefore(cutoff), "projection_binding");
        require(value.string("resultVersion").matches("judgment-v1-[0-9a-f]{64}"), "projection_version");
        if ("WITHHELD".equals(value.string("status"))) { require(!value.has("companies") && !value.has("conclusion"), "withheld_projection"); return; }
        require("PASS".equals(value.string("status")), "projection_status");
        for (String sid : value.object("sources").node().propertyNames()) {
            StrictJson.Obj source = value.object("sources").object(sid);
            require(sid.equals(source.string("evidenceId")) && source.string("bodySha256").equals(Canonical.sha256(source.string("fullBody").getBytes(java.nio.charset.StandardCharsets.UTF_8)))
                    && !Instant.parse(source.string("publishedAt")).isAfter(cutoff), "projection_source");
        }
        ObjectNode frozen = StrictJson.newObject(); frozen.set("sources", value.raw("sources")); var targets = frozen.putArray("targets");
        value.objects("companies").forEach(c -> {
            ObjectNode t = targets.addObject().put("companyId", c.string("companyId")).put("role", c.string("role"));
            require(Set.of("selected", "watch").contains(c.string("role")), "projection_role");
            t.set("previousJudgment", c.raw("previousJudgment"));
            t.set("sourceIds", c.raw("sourceIds"));
        });
        validateDraft(value, StrictJson.Obj.of(frozen));
    }
    private static void statementValue(StrictJson.Obj s, Set<String> allowed, int max) {
        String text = s.string("text"); List<String> ids = s.strings("evidenceIds");
        require(!text.isBlank() && text.codePointCount(0, text.length()) <= max && !ids.isEmpty() && ids.size() <= 6 && Set.copyOf(ids).size() == ids.size() && allowed.containsAll(ids), "statement");
    }
    private static void require(boolean ok, String reason) { if (!ok) throw new IllegalArgumentException("Judgment update rejected: " + reason); }
}
