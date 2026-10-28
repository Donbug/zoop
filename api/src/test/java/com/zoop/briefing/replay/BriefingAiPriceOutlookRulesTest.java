package com.zoop.briefing.replay;

import com.zoop.common.json.*;
import java.nio.file.*;
import java.util.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import static org.junit.jupiter.api.Assertions.*;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ObjectNode;

class BriefingAiPriceOutlookRulesTest {
    @TempDir Path root;
    ObjectNode review, price, row, draft;
    Map<String, JsonNode> receipts = new LinkedHashMap<>();
    ObjectNode statement() { var s=StrictJson.newObject().put("text", "합성 시험: 실제 이행과 가격은 구분한다.");s.putArray("evidenceIds").add("s1");return s; }
    void call(String phase, ObjectNode value, ObjectNode frozen, ObjectNode attempt) throws Exception {
        String prompt;
        try(var stream=getClass().getResourceAsStream("/briefing/prompts/company-outlook-v5/"+phase+".md")) {prompt=new String(stream.readAllBytes(),java.nio.charset.StandardCharsets.UTF_8);}
        var input=StrictJson.newObject();input.set("frozen",frozen.deepCopy()); if(phase.equals("verification"))input.set("draft",draft.deepCopy());else input.putNull("repair");
        var request=StrictJson.newObject().put("model","gpt-6-luna").put("store",false).put("instructions",prompt).put("input",Canonical.write(input));
        request.putObject("text").set("format",BriefingCompanySchemas.format("company_outlook_",phase,StrictJson.Obj.of(frozen)));
        byte[] qb=Canonical.bytes(request);String digest=Canonical.sha256(qb);
        var response=StrictJson.newObject().put("id","synthetic-"+phase).put("status","completed");response.putObject("usage").put("input_tokens",10).put("output_tokens",20);
        response.putArray("output").addObject().put("type","message").putArray("content").addObject().put("type","output_text").put("text",Canonical.write(value));
        byte[] rb=Canonical.bytes(response);Files.createDirectories(root.resolve("calls"));Files.write(root.resolve("calls/"+digest+".request.json"),qb);Files.write(root.resolve("calls/"+digest+".response.json"),rb);
        var receipt=StrictJson.newObject().put("stage","company_outlook_"+phase).put("model","gpt-6-luna").put("status","completed").put("responseId","synthetic-"+phase)
                .put("usageKnown",true).put("httpStatus",200).put("inputTokens",10).put("outputTokens",20).put("responseSha256",Canonical.sha256(rb));
        receipts.put(digest,receipt);attempt.put(phase+"RequestDigest",digest);row.put(phase+"RequestDigest",digest);
    }
    void fixture() throws Exception {
        review=StrictJson.newObject().put("roundId","r").put("date","2026-10-22").put("edition","morning").put("cutoff","2026-10-22T00:20:00Z").put("resultVersion","review-v1");
        review.putObject("sources").putObject("s1").put("quote","합성 계획이다.").put("publishedAt","2026-10-21T23:00:00Z");
        var c=review.putArray("companies").addObject().put("companyId","NASDAQ:A").put("companyName","합성 기업").put("role","selected").putNull("previous");
        c.putArray("sourceIds").add("s1");c.putObject("newInformation").putArray("evidenceIds").add("s1");
        price=StrictJson.newObject().put("resultVersion","price-v1");price.putObject("marketReference").put("status","unavailable").put("note","합성 미수집").putArray("indicators");
        var p=price.putArray("companies").addObject().put("companyId","NASDAQ:A").put("status","unavailable").put("currency","USD").put("provider","toss").put("cutoff","2026-10-22T00:20:00Z").put("reason","합성 미수집");p.putArray("responseSha256s");
        var f=StrictJson.newObject().put("promptVersion","company-outlook-v5").put("comparisonContract","edition-bound-v2").put("reviewVersion","review-v1").put("priceContextVersion","price-v1");
        for(var key:List.of("roundId","date","edition","cutoff"))f.set(key,review.get(key).deepCopy());f.set("sources",review.get("sources").deepCopy());f.set("marketReference",price.get("marketReference").deepCopy());
        var t=f.putArray("targets").addObject().put("companyId","NASDAQ:A").put("companyName","합성 기업").put("role","selected");t.putArray("sourceIds").add("s1");t.set("observedMovement",p.deepCopy());t.putObject("previous").put("status","unavailable");
        t.putArray("facts").addObject().put("text","합성 계획이다.").putArray("evidenceIds").add("s1");f.put("inputSha256",Canonical.digest(f));
        draft=StrictJson.newObject();var d=draft.putArray("companies").addObject().put("companyId","NASDAQ:A").put("assessment","watch");
        for(var key:List.of("impact","outlook"))d.set(key,statement());d.putArray("conditions").add(statement());d.putArray("risks").add(statement());
        var cmp=statement().put("status","unavailable").putNull("previousResultVersion");d.set("comparison",cmp);
        row=StrictJson.newObject().put("status","PASS").put("generatedAt","2026-10-24T00:00:00Z");for(var key:List.of("roundId","date","edition","cutoff"))row.set(key,f.get(key).deepCopy());row.set("frozen",f);row.set("draft",draft);
        var a=row.putArray("attempts").addObject();a.set("draft",draft.deepCopy());var v=StrictJson.newObject();v.putArray("checks").addObject().put("companyId","NASDAQ:A").put("supported",true).put("reason","합성 검증");a.set("verification",v);
        call("generation",draft,f,a);call("verification",v,f,a);row.put("resultVersion","ai-price-v1-"+Canonical.digest(row));
    }
    ObjectNode apply() {return BriefingAiPriceOutlookRules.apply(StrictJson.Obj.of(row),StrictJson.Obj.of(review),StrictJson.Obj.of(price),List.of(),receipts,root,new HashSet<>());}
    @Test void bindsProviderBytesAndKeepsOriginalReview() throws Exception {fixture();var original=review.deepCopy();var result=apply();assertEquals("PASS",result.path("status").stringValue());assertEquals(original,review);BriefingAiPriceOutlookRules.validateProjection(StrictJson.Obj.of(result),StrictJson.Obj.of(review),StrictJson.Obj.of(price));}
    @Test void rejectsChangedPriceInputAndRawModelResponse() throws Exception {fixture();((ObjectNode)price.path("companies").get(0)).put("reason","다른 값");assertThrows(IllegalArgumentException.class,this::apply);fixture();var path=Files.list(root.resolve("calls")).filter(p->p.toString().endsWith("response.json")).findFirst().orElseThrow();Files.writeString(path,"{}");assertThrows(IllegalArgumentException.class,this::apply);}
    @Test void rejectsEditingTheValidatedModelProjection() throws Exception {fixture();var result=apply();((ObjectNode)result.path("companies").get(0).path("outlook")).put("text","다른 결론");assertThrows(IllegalArgumentException.class,()->BriefingAiPriceOutlookRules.validateProjection(StrictJson.Obj.of(result),StrictJson.Obj.of(review),StrictJson.Obj.of(price)));}
}
