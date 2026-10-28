package com.zoop.briefing.impact;

import com.zoop.briefing.query.BriefingQueryService;
import com.zoop.briefing.storage.BriefingRound;
import com.zoop.common.exception.*;
import com.zoop.common.json.Canonical;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.jdbc.core.JdbcTemplate;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;
import java.nio.file.*;
import java.time.*;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

/** Authored unit fixture only; no provider call or real-news provenance claim. */
class BriefingImpactReviewServiceTest {
    @TempDir Path directory;
    final JsonMapper mapper=JsonMapper.builder().build();
    final BriefingQueryService briefings=mock(BriefingQueryService.class);
    final JdbcTemplate jdbc=mock(JdbcTemplate.class);
    final Instant cutoff=Instant.parse("2026-10-22T08:30:00Z");
    final Clock clock=Clock.fixed(Instant.parse("2026-10-27T02:00:00Z"),ZoneOffset.UTC);
    ObjectNode root,basis,assessment,detail;
    @BeforeEach void setup() throws Exception {
        String quote="A😀 company signs a contract.";
        int length=quote.codePointCount(0,quote.length());
        var payload=mapper.createObjectNode();
        payload.putArray("items").addObject().put("eventId","issue").put("title","Issue").putArray("companies")
                .addObject().put("id","company").put("name","Company");
        var round=new BriefingRound("round",LocalDate.parse("2026-10-22"),"evening",cutoff,null,cutoff,true,"published",
                cutoff.plusSeconds(10),cutoff,null,payload,mapper.createObjectNode(),null);
        when(briefings.impactBasis("round","issue","request")).thenReturn(round);
        when(jdbc.queryForObject("SELECT payload_sha256 FROM briefing_rounds WHERE id=?",String.class,"round")).thenReturn("a".repeat(64));
        detail=mapper.createObjectNode();
        var evidence=detail.putArray("evidence").addObject().put("id","original-evidence").put("documentId","document")
                .put("documentVersion","sha256-"+"b".repeat(64)).put("quote",quote).put("quoteVerified",true)
                .put("title","Authored test").put("url","https://example.test/test").put("publishedAt","2026-10-22T07:00:00Z");
        evidence.putObject("bodyContext").put("text",quote).put("start",100).put("end",100+length);
        when(briefings.getItem("round","issue","request")).thenReturn(detail);
        root=mapper.createObjectNode().put("schemaVersion","zoop-briefing-impact-reviews-1")
                .put("sourceKind","actual").put("executionMode","live").put("recordingKind","provider")
                .put("inputScope","preserved_quote_context").put("generationModel","gpt-6-luna").put("verifierModel","jev-1.14.0");
        var entry=root.putArray("reviews").addObject().put("assessedAt","2026-10-27T01:00:00Z");
        basis=entry.putObject("basis").put("roundId","round").put("eventId","issue")
                .put("dataAsOf",cutoff.toString()).put("publicationSha256","a".repeat(64));
        basis.putArray("companies").addObject().put("id","company").put("name","Company");
        basis.set("evidence",detail.path("evidence").deepCopy());
        entry.put("inputDigest",Canonical.digest(basis));
        var proofs=entry.putArray("proofs");Files.createDirectory(directory.resolve("receipts"));
        for (String stage:new String[]{"impact","verify-impact"}) {
            String model=stage.equals("impact")?"gpt-6-luna":"jev-1.14.0";
            var receipt=mapper.createObjectNode().put("format","zoop-live-receipt-1").put("stage",stage);
            receipt.putObject("http").put("status",200).put("bodyText","{}").put("bodySha256",Canonical.sha256("{}"));
            receipt.putObject("model").put("requested",model).put("reported",model);
            byte[] raw=mapper.writeValueAsBytes(receipt);Files.write(directory.resolve("receipts/"+stage+".json"),raw);
            proofs.addObject().put("path","receipts/"+stage+".json").put("bytes",raw.length).put("sha256",Canonical.sha256(raw));
        }
        assessment=entry.putArray("assessments").addObject().put("companyId","company").put("companyName","Company")
                .put("status","verified").put("label","positive").put("targetVerdict","supported");
        assessment.putArray("evidence").addObject().put("id","quote").put("effect","positive").put("quote",quote)
                .put("articleId","document").put("articleVersion","sha256-"+"b".repeat(64))
                .put("title","Authored test").put("url","https://example.test/test").put("publishedAt","2026-10-22T07:00:00Z")
                .put("start",100).put("end",100+length).put("sourceEvidenceId","original-evidence");
        nativeProofs("positive");
    }
    void nativeProofs(String effect) throws Exception {
        Files.createDirectories(directory.resolve("requests"));
        var entry=(ObjectNode)root.path("reviews").get(0);var proofs=entry.putArray("proofs");
        String quote=detail.path("evidence").get(0).path("quote").asString();
        for(String stage:new String[]{"impact","verify-impact"}) {
            boolean generation=stage.equals("impact");String model=generation?"gpt-6-luna":"jev-1.14.0";
            var request=mapper.createObjectNode().put("stage",stage).put("bindingIdentity","f".repeat(64))
                    .put("provider",generation?"openai-compatible":"typesafe-native");
            var body=request.putObject("body").put("model",model);
            var names=mapper.createArrayNode().add("Company");
            var relation=BriefingNativeImpactPolicy.relation("company",names,"issue","Issue",!generation);
            ObjectNode response=mapper.createObjectNode().put("model",model);
            if(generation) {
                request.put("schemaDigest",BriefingNativeImpactPolicy.POLICY.path("generationSchemaDigest").asString())
                        .put("promptVersion",BriefingNativeImpactPolicy.POLICY.path("generationPromptVersion").asString()).putNull("expect");
                body.putObject("response_format").putObject("json_schema").set("schema",BriefingNativeImpactPolicy.POLICY.path("generationSchema"));
                var in=mapper.createObjectNode();in.set("relation",relation);
                in.putArray("companies").add(relation.path("subject"));
                in.putArray("relationQuotes").addObject().put("quoteId","original-evidence").put("text",quote);
                in.putArray("documents").addObject().put("documentId","document").put("documentVersion","sha256-"+"b".repeat(64)).put("title","Authored test").put("text",quote);
                var envelope=mapper.createObjectNode().put("stage","impact");envelope.set("input",in);
                var messages=body.putArray("messages");messages.addObject().put("role","system").put("content",BriefingNativeImpactPolicy.POLICY.path("generationSystem").asString());
                messages.addObject().put("role","user").put("content",envelope.toString());
                var answer=mapper.createObjectNode().put("schemaVersion","zoop-impact-response-1").put("producerVersion","zoop-impact-producer-1");
                var proposal=answer.putArray("impacts").addObject().put("impactedCompanyId","company");proposal.putArray("opposing");
                proposal.putArray("supporting").addObject().put("documentId","document").put("documentVersion","b".repeat(64)).put("quote",quote);
                response.putArray("choices").addObject().put("finish_reason","stop").putObject("message").put("content",answer.toString());
            } else {
                request.put("schemaDigest",BriefingNativeImpactPolicy.POLICY.path("adapterIdentity").asString());
                request.putObject("expect").put("kind","verify-impact").putArray("quoteIds").add("quote");
                var state=body.putObject("state");state.set("relation",relation);state.set("target",relation.path("subject"));
                state.putArray("quotes").addObject().put("label","Q1").put("text",quote);
                body.set("questions",BriefingNativeImpactPolicy.questions(1));
                var answers=response.putObject("answers");choice(answers.putObject("target"),"supported",false);
                choice(answers.putObject("quote-0"),effect,true);
            }
            request.put("requestDigest",Canonical.digest(body));
            var receipt=mapper.createObjectNode().put("format","zoop-live-receipt-1").put("stage",stage)
                    .put("bindingIdentity","f".repeat(64)).put("requestDigest",Canonical.digest(body));receipt.set("expect",request.path("expect"));
            receipt.putObject("model").put("requested",model).put("reported",model);
            receipt.putObject("http").put("status",200).put("truncated",false).put("bodyText",response.toString()).put("bodySha256",Canonical.sha256(response.toString()));
            byte[] raw=mapper.writeValueAsBytes(receipt);Files.write(directory.resolve("receipts/"+stage+".json"),raw);
            Files.write(directory.resolve("requests/"+stage+".json"),mapper.writeValueAsBytes(request));
            proofs.addObject().put("path","receipts/"+stage+".json").put("sha256",Canonical.sha256(raw)).put("bytes",raw.length);
        }
    }
    void choice(ObjectNode answer,String choice,boolean effect) {
        answer.put("type","choice").put("choice",choice).put("confidence",.95);var probabilities=answer.putObject("probabilities");
        for(String key:effect?new String[]{"positive","negative","neutral","uncertain"}:new String[]{"supported","contradicted","insufficient"})probabilities.put(key,choice.equals(key)?1.0:0.0);
    }
    BriefingImpactReviewService service() throws Exception {
        byte[] bytes=mapper.writeValueAsBytes(root);Path file=directory.resolve("manifest.json");Files.write(file,bytes);
        return new BriefingImpactReviewService(briefings,jdbc,mapper,clock,file.toRealPath().toString(),Canonical.sha256(bytes));
    }
    @Test void preservesTheHistoricalBasisAndExactUnicodeSpan() throws Exception {
        var out=service().get("round","issue",null,"request");
        assertNull(out.graphVersion());assertEquals("historical_reassessment",out.reviewContext().mode());
        assertEquals("positive",out.companies().getFirst().assessments().getFirst().label());
        assertTrue(out.companies().getFirst().assessments().getFirst().evidence().getFirst().quote().contains("😀"));
    }
    @Test void absentConfigurationMeansMissingNotUndetermined() {
        var out=new BriefingImpactReviewService(briefings,jdbc,mapper,clock,"","").get("round","issue",null,"request");
        assertEquals("unavailable",out.status());assertNull(out.reviewContext());assertTrue(out.companies().isEmpty());
    }
    @Test void changedManifestOrReceiptFailsClosed() throws Exception {
        var first=service();Files.writeString(directory.resolve("manifest.json"),"{}");
        assertThrows(CustomException.class,()->first.get("round","issue",null,"request"));
        var second=service();Files.writeString(directory.resolve("receipts/impact.json"),"{}");
        assertThrows(CustomException.class,()->second.get("round","issue",null,"request"));
    }
    @Test void publicationMismatchAndVersionMismatchCannotBeBypassed() throws Exception {
        when(jdbc.queryForObject("SELECT payload_sha256 FROM briefing_rounds WHERE id=?",String.class,"round")).thenReturn("c".repeat(64));
        var reader=service();assertThrows(CustomException.class,()->reader.get("round","issue",null,"request"));
        assertThrows(CustomException.class,()->reader.get("round","issue","other","request"));
    }
    @Test void foreignCompanyQuoteOrSourceCannotBeReused() throws Exception {
        assessment.put("companyId","other");var reader=service();
        assertThrows(CustomException.class,()->reader.get("round","issue",null,"request"));
        assessment.put("companyId","company");((ObjectNode)assessment.path("evidence").get(0)).put("sourceEvidenceId","other");
        var second=service();assertThrows(CustomException.class,()->second.get("round","issue",null,"request"));
    }
    @Test void producerLabelCannotOverrideTheVerifierEffects() throws Exception {
        assessment.put("label","negative");var reader=service();
        assertThrows(CustomException.class,()->reader.get("round","issue",null,"request"));
    }
    @Test void emptySuccessBodyAndAnotherCompanyRequestCannotBeUsedAsVerification() throws Exception {
        Path file=directory.resolve("receipts/verify-impact.json");var receipt=(ObjectNode)mapper.readTree(Files.readAllBytes(file));
        ((ObjectNode)receipt.path("http")).put("bodyText","{}").put("bodySha256",Canonical.sha256("{}"));
        byte[] raw=mapper.writeValueAsBytes(receipt);Files.write(file,raw);
        var proof=(ObjectNode)root.path("reviews").get(0).path("proofs").get(1);proof.put("sha256",Canonical.sha256(raw)).put("bytes",raw.length);
        var first=service();assertThrows(CustomException.class,()->first.get("round","issue",null,"request"));
        nativeProofs("positive");Path requestFile=directory.resolve("requests/verify-impact.json");
        var request=(ObjectNode)mapper.readTree(Files.readAllBytes(requestFile));
        ((ObjectNode)request.path("body").path("state").path("target")).putArray("names").add("Other Company");
        request.put("requestDigest",Canonical.digest(request.path("body")));Files.write(requestFile,mapper.writeValueAsBytes(request));
        receipt=(ObjectNode)mapper.readTree(Files.readAllBytes(file));receipt.set("requestDigest",request.path("requestDigest"));
        raw=mapper.writeValueAsBytes(receipt);Files.write(file,raw);proof=(ObjectNode)root.path("reviews").get(0).path("proofs").get(1);
        proof.put("sha256",Canonical.sha256(raw)).put("bytes",raw.length);
        var second=service();assertThrows(CustomException.class,()->second.get("round","issue",null,"request"));
    }
    @Test void rehashedManifestEffectsMustStillMatchTheSavedNativeAnswer() throws Exception {
        assessment.put("label","negative");((ObjectNode)assessment.path("evidence").get(0)).put("effect","negative");
        var reader=service();assertThrows(CustomException.class,()->reader.get("round","issue",null,"request"));
    }
    @Test void uncertainEffectsProduceUndeterminedAndMissingVerifierIsRefused() throws Exception {
        assessment.put("label","undetermined");((ObjectNode)assessment.path("evidence").get(0)).put("effect","uncertain");
        nativeProofs("uncertain");
        assertEquals("undetermined",service().get("round","issue",null,"request").companies().getFirst().assessments().getFirst().label());
        ((tools.jackson.databind.node.ArrayNode)root.path("reviews").get(0).path("proofs")).remove(1);
        var reader=service();assertThrows(CustomException.class,()->reader.get("round","issue",null,"request"));
    }
    @Test void currentRightsFailureIsNotReportedAsMissing() throws Exception {
        when(briefings.getItem("round","issue","request")).thenThrow(new CustomException(ErrorCode.SOURCE_UNAVAILABLE));
        var reader=service();assertThrows(CustomException.class,()->reader.get("round","issue",null,"request"));
    }
    void withFactContext() {
        root.put("schemaVersion","zoop-briefing-impact-reviews-2").put("citationPolicy","complete-source-paragraph-1")
                .put("previousManifestSha256","c".repeat(64));
        ((ObjectNode)root.path("reviews").get(0)).putObject("citationRepair").put("policy","complete-source-paragraph-1")
                .put("generation","reused").put("effects","independent_recheck").put("previousResultSha256","d".repeat(64));
        ObjectNode fact=((ObjectNode)assessment.path("evidence").get(0)).deepCopy();
        fact.remove("effect");assessment.putArray("facts").add(fact);
    }
    @Test void undeterminedRetainsExactFactsSeparatelyFromQuoteEffects() throws Exception {
        withFactContext();assessment.put("label","undetermined");
        ((ObjectNode)assessment.path("evidence").get(0)).put("effect","uncertain");
        nativeProofs("uncertain");
        var result=service().get("round","issue",null,"request");
        var a=result.companies().getFirst().assessments().getFirst();
        assertEquals("undetermined",a.label());assertEquals(1,a.facts().size());
        assertEquals("complete-source-paragraph-1",result.reviewContext().citationPolicy());
        assertTrue(a.facts().getFirst().quote().contains("😀"));
    }
    @Test void noDirectionalEvidenceDoesNotHideOriginalFacts() throws Exception {
        withFactContext();assessment.put("status","no-evidence").putNull("label");assessment.putArray("evidence");
        var result=service().get("round","issue",null,"request");
        assertEquals("unavailable",result.status());
        assertEquals(1,result.companies().getFirst().assessments().getFirst().facts().size());
    }
    @Test void factsCannotBeFabricatedOrAssignedAnUnverifiedEffect() throws Exception {
        withFactContext();var fact=(ObjectNode)assessment.path("facts").get(0);
        String original=fact.path("quote").asString();fact.put("quote","Fabricated statement.");
        var first=service();assertThrows(CustomException.class,()->first.get("round","issue",null,"request"));
        fact.put("quote",original).put("effect","positive");
        var second=service();assertThrows(CustomException.class,()->second.get("round","issue",null,"request"));
    }
    @Test void factSourceVersionAndSourceDateRemainBound() throws Exception {
        withFactContext();var fact=(ObjectNode)assessment.path("facts").get(0);
        fact.put("articleVersion","other");var first=service();
        assertThrows(CustomException.class,()->first.get("round","issue",null,"request"));
        fact.put("articleVersion","sha256-"+"b".repeat(64)).put("publishedAt","2026-10-23T00:00:00Z");
        var second=service();assertThrows(CustomException.class,()->second.get("round","issue",null,"request"));
    }
}
