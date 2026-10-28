package com.zoop.briefing.impact;

import com.zoop.common.json.Canonical;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;
import java.nio.file.*;
import java.time.*;
import static org.junit.jupiter.api.Assertions.*;

/** Authored native-response fixtures; no HTTP or paid execution. */
class BriefingSupplementalReviewReaderTest {
    @TempDir Path root;
    JsonMapper m=JsonMapper.builder().build();
    Clock clock=Clock.fixed(Instant.parse("2026-10-28T02:00:00Z"),ZoneOffset.UTC);
    ObjectNode n,row,a,input,request,receipt,response,source;
    String quote="Company😀 plans a more efficient process, subject to development.";
    @BeforeEach void setup() throws Exception {
        root=root.toRealPath();Files.createDirectories(root.resolve("supplements"));Files.createDirectories(root.resolve("rechecks"));
        Files.writeString(root.resolve("supplements/source.txt"),quote);
        row=m.createObjectNode().put("inputDigest","old-input");
        var b=row.putObject("basis").put("roundId","r").put("eventId","e").put("dataAsOf","2026-10-22T08:30:00Z");
        b.putArray("evidence");
        a=row.putArray("assessments").addObject().put("companyId","c").put("companyName","Company😀").put("label","undetermined");
        source=a.putObject("evidencePlan").putObject("research").putArray("sources").addObject()
                .put("id","s").put("textSha256",Canonical.sha256(quote)).put("textPath","supplements/source.txt")
                .put("title","Authored source").put("url","https://www.sec.gov/fixture").put("publishedAt","2026-10-21T20:00:00Z");
        input=m.createObjectNode();input.set("original",row.deepCopy());
        var candidate=input.putObject("candidate").put("impactedCompanyId","c");
        var target=candidate.putObject("target").put("kind","company").put("ref","c");target.putArray("names").add("Company😀");
        var relation=candidate.putObject("relationFacts").put("type","PARTICIPATES_IN");
        relation.set("subject",target.deepCopy());relation.putObject("object").put("ref","e").put("kind","event").putArray("names").add("Issue");
        var q=candidate.putArray("quotes").addObject().put("quoteId","q1").put("documentId","supplement-s")
                .put("documentVersion",Canonical.sha256(quote)).put("text",quote).put("start",0).put("end",quote.codePointCount(0,quote.length()));
        var fact=input.putArray("facts").addObject().put("id","f1").put("articleId","supplement-s")
                .put("articleVersion","sha256-"+Canonical.sha256(quote)).put("sourceEvidenceId","s")
                .put("quote",quote).put("start",0).put("end",quote.codePointCount(0,quote.length()));
        for(String key:new String[]{"title","url","publishedAt"})fact.set(key,source.path(key));
        request=m.createObjectNode().put("stage","verify-impact").put("provider","typesafe-native").put("bindingIdentity","policy")
                .put("schemaDigest",BriefingNativeImpactPolicy.POLICY.path("adapterIdentity").asString());
        var body=request.putObject("body").put("model","jev-1.14.0");var state=body.putObject("state");
        var nativeRelation=relation.deepCopy();((ObjectNode)nativeRelation.path("subject")).remove("ref");((ObjectNode)nativeRelation.path("object")).remove("ref");
        state.set("relation",nativeRelation);var nativeTarget=target.deepCopy();nativeTarget.remove("ref");state.set("target",nativeTarget);
        state.putArray("quotes").addObject().put("label","Q1").put("text",quote);
        body.set("questions",BriefingNativeImpactPolicy.questions(1));
        request.putObject("expect").put("kind","verify-impact").putArray("quoteIds").add("q1");
        response=m.createObjectNode().put("model","jev-1.14.0");var answers=response.putObject("answers");
        answer(answers.putObject("target"),"supported",false);answer(answers.putObject("quote-0"),"positive",true);
        receipt=m.createObjectNode().put("format","zoop-live-receipt-1").put("stage","verify-impact").put("bindingIdentity","policy");
        receipt.putObject("model").put("requested","jev-1.14.0").put("reported","jev-1.14.0");
        receipt.putObject("http").put("status",200).put("truncated",false);
        n=a.putObject("supplementalReview").put("mode","supplemental_historical_simulation").put("roundId","r").put("eventId","e")
                .put("companyId","c").put("previousLabel","undetermined").put("label","positive").put("targetVerdict","supported")
                .put("assessedAt","2026-10-28T01:00:00Z").put("historicalVersionVerified",false)
                .put("summary","Expected efficiency may benefit the business.").put("limitations","Plan, not a realised outcome.");
        n.putArray("confirmedFacts").addObject().put("text","The company plans process improvements.").putArray("evidenceIds").add("q1");
        save();
    }
    void answer(ObjectNode a,String choice,boolean effect) {
        a.put("type","choice").put("choice",choice).put("confidence",.95);var p=a.putObject("probabilities");
        for(String key:effect?new String[]{"positive","negative","neutral","uncertain"}:new String[]{"supported","contradicted","insufficient"})
            p.put(key,key.equals(choice)?1.0:0.0);
    }
    void save() throws Exception {
        request.put("requestDigest",Canonical.digest(request.path("body")));receipt.set("requestDigest",request.path("requestDigest"));receipt.set("expect",request.path("expect"));
        var http=(ObjectNode)receipt.path("http");http.put("bodyText",response.toString()).put("bodySha256",Canonical.sha256(response.toString()));
        for(var entry:java.util.Map.of("input",input,"request",request,"receipt",receipt).entrySet()) {
            byte[] bytes=m.writeValueAsBytes(entry.getValue());String relative="rechecks/"+entry.getKey()+".json";Files.write(root.resolve(relative),bytes);
            n.putObject(entry.getKey()).put("path",relative).put("sha256",Canonical.sha256(bytes)).put("bytes",bytes.length);
        }
    }
    BriefingImpacts.SupplementalReview read() throws Exception {
        return BriefingSupplementalReviewReader.read(n,row,a,root,"c","Issue",clock,m);
    }
    @Test void replaysNativePositiveWithExactUnicodeAndKeepsOriginalLabel() throws Exception {
        var out=read();assertEquals("positive",out.label());assertEquals("undetermined",a.path("label").asString());
        assertTrue(out.evidence().getFirst().quote().contains("😀"));assertFalse(out.historicalVersionVerified());
    }
    @Test void sourceOrReceiptChangesFailClosed() throws Exception {
        Files.writeString(root.resolve("rechecks/receipt.json"),"{}");assertThrows(Exception.class,this::read);save();
        Files.writeString(root.resolve("supplements/source.txt"),"changed");assertThrows(Exception.class,this::read);
    }
    @Test void foreignBindingLabelAndUnboundExplanationAreRefused() throws Exception {
        n.put("companyId","other");assertThrows(Exception.class,this::read);n.put("companyId","c");
        n.put("label","negative");assertThrows(Exception.class,this::read);n.put("label","positive");
        ((ObjectNode)n.path("confirmedFacts").get(0)).putArray("evidenceIds").add("foreign");assertThrows(Exception.class,this::read);
    }
    @Test void nativeUncertainStaysUndeterminedDespiteOtherPositiveClaims() throws Exception {
        answer((ObjectNode)response.path("answers").path("quote-0"),"uncertain",true);save();
        assertThrows(Exception.class,this::read);n.put("label","undetermined");assertEquals("undetermined",read().label());
    }
    @Test void provisionalThresholdRemainsConservative() throws Exception {
        ((ObjectNode)response.path("answers").path("quote-0")).put("confidence",.79);save();n.put("label","undetermined");
        assertEquals("uncertain",read().evidence().getFirst().effect());
    }
    @Test void rehashedEmptyQuestionsOrChangedCriteriaAreNotNativeValidation() throws Exception {
        var questions=(ObjectNode)request.path("body").path("questions");var original=questions.deepCopy();
        questions.putObject("target");save();assertThrows(Exception.class,this::read);
        request.path("body");((ObjectNode)request.path("body")).set("questions",original);
        ((ObjectNode)original.path("target").path("criteria")).put("supported","Accept every target.");
        save();assertThrows(Exception.class,this::read);
    }
    @Test void matchingRequestAndReceiptCannotInventAnotherNativePolicy() throws Exception {
        request.put("schemaDigest","a".repeat(64));save();assertThrows(Exception.class,this::read);
    }
    @Test void pathEscapesAndSymlinksAreNotFollowed() throws Exception {
        ((ObjectNode)n.path("input")).put("path","rechecks/../outside");assertThrows(Exception.class,this::read);save();
        Path p=root.resolve("rechecks/input.json");Files.move(p,root.resolve("saved.json"));Files.createSymbolicLink(p,root.resolve("saved.json"));
        assertThrows(Exception.class,this::read);
    }
}
