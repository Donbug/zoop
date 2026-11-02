package com.zoop.briefing.personal;

import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import org.springframework.stereotype.Service;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ObjectNode;
import tools.jackson.databind.json.JsonMapper;
import java.util.*;

/** Only restore a checked revision for this member's exact current selection; GET never calls a model. */
@Service
public class PersonalAiRead {
    static final String VERSION="personal-briefing-v1";
    private final PersonalAiRepository repository;
    private final JsonMapper json=JsonMapper.builder().build();
    public PersonalAiRead(PersonalAiRepository repository){this.repository=repository;}

    static ObjectNode basis(JsonNode selection) {
        var j=JsonMapper.builder().build();var out=j.createObjectNode().put("roundId",selection.path("roundId").asString())
            .put("poolVersion",selection.path("poolVersion").asString());
        var b=out.putObject("basis");
        for(String key:List.of("holdings","watchlist"))selection.path("basis").path(key).valueStream().map(JsonNode::asString)
            .distinct().sorted().forEach(b.putArray(key)::add);
        var issues=out.putArray("issues");
        for(var item:selection.path("items")) {
            var row=issues.addObject().put("issueId",item.path("issueId").asString());
            item.path("matches").valueStream().map(m->m.path("companyId").asString()).sorted().forEach(row.putArray("companyIds")::add);
        }
        return out;
    }

    public JsonNode read(String memberId,JsonNode selection) {
        var missing=json.createObjectNode().put("status","unavailable").put("reason","not_generated_for_current_selection");
        if(selection.path("items").isEmpty())return missing.put("reason","no_qualified_issues");
        var saved=repository.find(memberId,selection.path("roundId").asString(),basis(selection)).orElse(null);
        if(saved==null)return missing;
        try {
            validate(saved,basis(selection));
            // Exact selection/current source rights have already passed PersonalBriefingService.
            var out=(ObjectNode)saved.result().deepCopy();out.put("status","available");
            out.remove(List.of("selectionBasis","verification"));
            return out;
        } catch(IllegalArgumentException|StrictJson.Malformed bad) {
            return missing.put("reason","stored_analysis_proof_invalid");
        }
    }

    static void validate(PersonalAiRepository.Saved saved,JsonNode expectedBasis) {
        var j=JsonMapper.builder().build();var input=saved.input();var result=saved.result();
        require(input.path("selectionBasis").equals(expectedBasis) && result.path("selectionBasis").equals(expectedBasis));
        require(VERSION.equals(result.path("schemaVersion").asString()) && "PASS".equals(result.path("status").asString())
            && "gpt-6-luna".equals(result.path("model").asString()) && Set.of(VERSION,VERSION+".1").contains(result.path("promptVersion").asString())
            && result.path("roundId").equals(input.path("roundId")) && result.path("cutoff").equals(input.path("cutoff"))
            && result.path("inputSha256").equals(input.path("inputSha256")));
        var unsigned=(ObjectNode)result.deepCopy();unsigned.remove("resultVersion");
        require((VERSION+"-"+Canonical.sha256(Canonical.bytes(unsigned))).equals(result.path("resultVersion").asString()));
        var checked=result.path("verification");require(checked.path("overviewSupported").asBoolean());
        require(input.path("roundId").equals(expectedBasis.path("roundId")));
        Map<String,Set<String>> expected=new HashMap<>();
        for(var issue:expectedBasis.path("issues")) {
            Set<String> ids=new HashSet<>();issue.path("companyIds").forEach(id->ids.add(id.asString()));
            require(expected.put(issue.path("issueId").asString(),ids)==null);
        }
        Set<String> issueIds=new HashSet<>();Set<String> allEvidence=new HashSet<>();
        for(var issue:input.path("issues")) {
            String iid=issue.path("issueId").asString();require(issueIds.add(iid));Set<String> companyIds=new HashSet<>();
            for(var target:issue.path("targets")) {
                String cid=target.path("companyId").asString();require(companyIds.add(cid));
                require(checked.path("issues").path(iid).path(cid).path("supported").asBoolean());
                var company=result.path("draft").path("issues").path(iid).path("companies").path(cid);require(company.isObject());
                Set<String> ids=new HashSet<>();target.path("evidenceIds").forEach(id->ids.add(id.asString()));allEvidence.addAll(ids);
                for(String f:List.of("keyPoint","confirmedFact","businessImpact","forMyStocks","previousChange","nextCheck")) statement(company.path(f),ids);
                require(List.of("positive","negative","mixed","watch").contains(company.path("direction").asString()));
                if(!"available".equals(target.path("previous").path("status").asString()))
                    require("unavailable".equals(company.path("previousChange").path("status").asString()));
                if(!company.path("priceObservation").isNull()) {
                    require("available".equals(target.path("frozenPrice").path("status").asString()));statement(company.path("priceObservation"),ids);
                }
            }
            require(companyIds.equals(expected.get(iid)) && companyIds.equals(result.path("draft").path("issues").path(iid).path("companies").propertyNames()));
        }
        require(issueIds.equals(expected.keySet()) && issueIds.equals(result.path("draft").path("issues").propertyNames()));statement(result.path("draft").path("overview"),allEvidence);
        require(saved.proof().isArray() && saved.proof().size()==2);Set<String> stages=new HashSet<>();
        for(var proof:saved.proof()) {
            String reqRaw=proof.path("request").asString(),resRaw=proof.path("response").asString();
            require(Canonical.sha256(reqRaw.getBytes(java.nio.charset.StandardCharsets.UTF_8)).equals(proof.path("requestSha256").asString())
                && Canonical.sha256(resRaw.getBytes(java.nio.charset.StandardCharsets.UTF_8)).equals(proof.path("responseSha256").asString()));
            var req=StrictJson.parseObject(reqRaw).node();var res=StrictJson.parseObject(resRaw).node();
            require("gpt-6-luna".equals(req.path("model").asString()) && !req.path("store").asBoolean(true)
                && "completed".equals(res.path("status").asString()) && !res.path("id").asString().isBlank()
                && res.path("usage").path("input_tokens").isIntegralNumber() && res.path("usage").path("output_tokens").isIntegralNumber());
            var data=StrictJson.parseObject(req.path("input").asString()).node();require(data.path("frozen").equals(input));
            String stage=req.path("text").path("format").path("name").asString();require(stages.add(stage));
            List<JsonNode> answers=new ArrayList<>();
            for(var message:res.path("output"))for(var part:message.path("content"))if("output_text".equals(part.path("type").asString()))answers.add(j.readTree(part.path("text").asString()));
            require(answers.size()==1);
            if("personal-analysis".equals(stage)) require(answers.getFirst().equals(result.path("draft")));
            else {require("personal-verification".equals(stage));require(data.path("draft").equals(result.path("draft")) && answers.getFirst().equals(checked));}
        }
        require(stages.equals(Set.of("personal-analysis","personal-verification")));
    }
    private static void statement(JsonNode value,Set<String> ids) {
        require(value.isObject() && !value.path("text").asString().isBlank() && !value.path("evidenceIds").isEmpty());
        Set<String> seen=new HashSet<>();for(var id:value.path("evidenceIds"))require(ids.contains(id.asString()) && seen.add(id.asString()));
    }
    private static void require(boolean value){if(!value)throw new IllegalArgumentException("personal_ai_proof_invalid");}
}
