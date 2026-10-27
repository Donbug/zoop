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
        payload.putArray("items").addObject().put("eventId","issue").putArray("companies")
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
    @Test void uncertainEffectsProduceUndeterminedAndMissingVerifierIsRefused() throws Exception {
        assessment.put("label","undetermined");((ObjectNode)assessment.path("evidence").get(0)).put("effect","uncertain");
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
