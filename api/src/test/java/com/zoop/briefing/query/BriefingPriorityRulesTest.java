package com.zoop.briefing.query;

import java.time.Instant;
import java.util.Set;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;
import static org.junit.jupiter.api.Assertions.*;

class BriefingPriorityRulesTest {
    private static final JsonMapper JSON = JsonMapper.builder().build();
    private ObjectNode example() throws Exception {
        try (var input = getClass().getResourceAsStream("/briefing/priority-authored.json")) {
            return (ObjectNode) JSON.readTree(input);
        }
    }
    private void valid(ObjectNode value) {
        BriefingPriorityRules.validate(value, "brf-test-2026-10-15-evening", Instant.parse("2026-10-15T08:30:00Z"),
                false, Set.of("brf-test-company"), Set.of("brf-test-evidence"));
    }
    @Test void relativeIssueDoesNotRaiseTheOriginalImportanceScore() throws Exception { valid(example()); }
    @Test void companyEvidenceAndAnalysisVersionStayBound() throws Exception {
        var value = example(); ((ObjectNode)value.at("/items/0/aiAnalyses/0")).put("companyId", "other");
        assertThrows(IllegalArgumentException.class, () -> valid(value));
        value.set("items", example().get("items"));
        ((ObjectNode)value.at("/items/0/aiAnalyses/0")).put("resultVersion", "wrong-version");
        assertThrows(IllegalArgumentException.class, () -> valid(value));
        value.set("items", example().get("items"));
        ((ObjectNode)value.at("/items/0/sources/0")).put("evidenceId", "other-evidence");
        assertThrows(IllegalArgumentException.class, () -> valid(value));
    }
    @Test void publicAnalysisCannotCarryPrivatePersonalProse() throws Exception {
        var value = example(); ((ObjectNode)value.at("/items/0/aiAnalyses/0")).put("forMyStocks", "private member text");
        assertThrows(IllegalArgumentException.class, () -> valid(value));
    }
    @Test void duplicateIssueAndUnconfirmedVerificationModeAreRejected() throws Exception {
        var value = example(); ((tools.jackson.databind.node.ArrayNode)value.get("items")).add(value.at("/items/0").deepCopy());
        assertThrows(IllegalArgumentException.class, () -> valid(value));
        value.set("items", example().get("items"));
        ((ObjectNode)value.at("/items/0/aiAnalyses/0")).put("verificationMode", "self_asserted");
        assertThrows(IllegalArgumentException.class, () -> valid(value));
    }
    @Test void personalSelectionCannotBorrowAnotherMembersCompanyScope() throws Exception {
        var common = example(); var personal = common.deepCopy();
        for (String k : java.util.List.of("generationVersion", "minimumShortfall", "legacyAnalysisScopeWarning")) personal.remove(k);
        personal.put("schemaVersion", "personal-relative-priority-view-v1"); personal.putArray("companyIds").add("brf-test-company");
        var item = (ObjectNode) personal.at("/items/0"); item.set("connections", item.remove("companies"));
        for (String k : java.util.List.of("importance", "whyNow", "analysisResultVersion", "prices")) item.remove(k);
        item.put("kind", "new_issue").putNull("price").putArray("priorAnalysis");
        var a = (ObjectNode)item.at("/aiAnalyses/0"); a.set("forMyStocks", a.remove("companyConnection"));
        ((ObjectNode)a.get("judgmentBasis")).put("promptVersion", "personal-impact-relative-v3");
        a.putObject("comparison").put("status", "newly_selected").putNull("baseline");
        assertDoesNotThrow(() -> BriefingPriorityRules.validate(personal, personal.path("roundId").asString(),
                Instant.parse(personal.path("cutoff").asString()), true, Set.of("brf-test-company"), Set.of("brf-test-evidence")));
        ((ObjectNode)a.get("judgmentBasis")).put("promptVersion", "common-impact-relative-v1");
        assertDoesNotThrow(() -> BriefingPriorityRules.validate(personal, personal.path("roundId").asString(),
                Instant.parse(personal.path("cutoff").asString()), true, Set.of("brf-test-company"), Set.of("brf-test-evidence")));
        ((ObjectNode)a.get("judgmentBasis")).put("promptVersion", "invented-version");
        assertThrows(IllegalArgumentException.class, () -> BriefingPriorityRules.validate(personal, personal.path("roundId").asString(),
                Instant.parse(personal.path("cutoff").asString()), true, Set.of("brf-test-company"), Set.of("brf-test-evidence")));
        ((ObjectNode)a.get("judgmentBasis")).put("promptVersion", "common-impact-relative-v1");
        assertThrows(IllegalArgumentException.class, () -> BriefingPriorityRules.validate(personal, personal.path("roundId").asString(),
                Instant.parse(personal.path("cutoff").asString()), true, Set.of("another-company"), Set.of("brf-test-evidence")));
    }
    @Test
    @org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable(named="BRIEFING_PRIORITY_RECORDS", matches=".+")
    void externallySuppliedSavedViewsMeetTheReadContractWithoutPublishingThem() throws Exception {
        int count = 0;
        for (String line : java.nio.file.Files.readAllLines(java.nio.file.Path.of(System.getenv("BRIEFING_PRIORITY_RECORDS")))) {
            var row = JSON.readTree(line); boolean personal = "personal".equals(row.path("scope").asString());
            var priority = row.path("priority"); java.util.Set<String> companies = new java.util.HashSet<>(), evidence = new java.util.HashSet<>();
            if (personal) companies.addAll(BriefingPriorityRules.strings(priority, "companyIds"));
            for (var item : priority.path("items")) {
                if (!personal) for (var company : item.path("companies")) companies.add(company.path("companyId").asString());
                for (var source : item.path("sources")) evidence.add(source.path("evidenceId").asString());
            }
            BriefingPriorityRules.validate(priority, row.path("roundId").asString(), Instant.parse(row.path("cutoff").asString()), personal, companies, evidence);
            count++;
        }
        assertEquals(24,count);
    }

}
