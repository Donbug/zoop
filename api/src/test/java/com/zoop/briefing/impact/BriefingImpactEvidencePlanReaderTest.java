package com.zoop.briefing.impact;

import com.zoop.common.json.Canonical;
import com.zoop.document.repository.*;
import com.zoop.document.evidence.service.EvidenceArtifactReader;
import org.junit.jupiter.api.*;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;
import java.nio.charset.StandardCharsets;
import java.time.*;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class BriefingImpactEvidencePlanReaderTest {
    final JsonMapper mapper=JsonMapper.builder().build();
    final DocumentRegistryRepository registry=mock(DocumentRegistryRepository.class);
    final EvidenceArtifactReader files=mock(EvidenceArtifactReader.class);
    final Instant published=Instant.parse("2026-10-21T20:01:00Z"),cutoff=Instant.parse("2026-10-22T00:20:00Z");
    ObjectNode plan,basis,quote;ArtifactRow artifact;
    BriefingImpactEvidencePlanReader reader;
    @BeforeEach void setup() {
        String prefix="x".repeat(2100)+"\n",q="Company A😀 may use Class C to finance growth, subject to approval.";
        byte[] bytes=(prefix+q).getBytes(StandardCharsets.UTF_8);String sha=Canonical.sha256(bytes);
        basis=mapper.createObjectNode();var source=basis.putArray("evidence").addObject().put("id","bound")
                .put("documentId","doc").put("documentVersion","sha256-"+sha).put("title","Test").put("url","https://example.test")
                .put("publishedAt",published.toString()).put("bodySha256",sha);
        source.putObject("bodyContext").put("start",0).put("end",1800).put("text","x".repeat(1800));
        artifact=new ArtifactRow("text","article_text","artifact-root:text",sha,bytes.length,"text/plain",published);
        when(registry.findVersion("doc","sha256-"+sha)).thenReturn(Optional.of(new VersionRow("doc","sha256-"+sha,
                "Test","Publisher","https://example.test",published,null,"datetime",null,"text",published)));
        when(registry.findArtifact("text")).thenReturn(Optional.of(artifact));when(files.read(artifact)).thenReturn(bytes);
        plan=mapper.createObjectNode().put("status","prepared_not_evaluated").put("preparedAt","2026-10-27T01:00:00Z").put("reason","More source context is available.");
        var fact=plan.putArray("existingEvidence").addObject().put("scope","issuer_explanation").put("note","Issuer explanation, not realized returns.");
        quote=fact.putObject("source").put("id","s1").put("sourceEvidenceId","bound").put("articleId","doc").put("articleVersion","sha256-"+sha)
                .put("title","Test").put("url","https://example.test").put("publishedAt",published.toString()).put("bodySha256",sha)
                .put("quote",q).put("start",prefix.length()).put("end",prefix.length()+q.codePointCount(0,q.length()));
        plan.putArray("collectionNeeds").addObject().put("kind","future_followup").put("what","Actual deployment")
                .put("why","Outcome check only").put("preferredSource","Company filings");
        reader=new BriefingImpactEvidencePlanReader(registry,files,Clock.fixed(Instant.parse("2026-10-27T02:00:00Z"),ZoneOffset.UTC));
    }
    @Test void readsExactRegisteredTextOutsideOldContextWithoutAssigningAnEffect() throws Exception {
        var out=reader.read(plan,basis,cutoff);
        assertEquals("prepared_not_evaluated",out.status());assertEquals(2101,out.existingEvidence().getFirst().source().start());
        assertTrue(out.existingEvidence().getFirst().source().quote().contains("😀"));
        assertEquals("future_followup",out.collectionNeeds().getFirst().kind());
    }
    @Test void rejectsModifiedBodyEvenIfReaderReturnsBytes() {
        when(files.read(artifact)).thenReturn("changed".getBytes(StandardCharsets.UTF_8));
        assertThrows(Exception.class,()->reader.read(plan,basis,cutoff));
    }
    @Test void rejectsForeignArticleOrSource() {
        quote.put("sourceEvidenceId","foreign");
        assertThrows(Exception.class,()->reader.read(plan,basis,cutoff));verifyNoInteractions(files);
    }
    @Test void refusesFutureSourceAndQuoteOutsideBody() {
        assertThrows(Exception.class,()->reader.read(plan,basis,published.minusSeconds(1)));
        quote.put("end",99999);assertThrows(Exception.class,()->reader.read(plan,basis,cutoff));
    }
    @Test void preparationCannotClaimVerifiedPolarity() {
        plan.put("label","positive");assertThrows(Exception.class,()->reader.read(plan,basis,cutoff));
        plan.remove("label");quote.put("effect","positive");assertThrows(Exception.class,()->reader.read(plan,basis,cutoff));
    }
}
