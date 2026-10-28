package com.zoop.briefing.impact;

import com.zoop.common.json.Canonical;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;
import java.nio.file.*;
import java.time.*;
import static org.junit.jupiter.api.Assertions.*;

/** Authored source fixtures. No remote requests or AI calls. */
class BriefingSupplementalEvidenceReaderTest {
    @TempDir Path root;
    final JsonMapper mapper=JsonMapper.builder().build();
    final Instant cutoff=Instant.parse("2026-10-22T00:20:00Z");
    final Clock clock=Clock.fixed(Instant.parse("2026-10-28T01:00:00Z"),ZoneOffset.UTC);
    ObjectNode node,basis,source;
    @BeforeEach void setup() throws Exception {
        root=root.toRealPath();
        Files.createDirectory(root.resolve("supplements"));
        String excerpt="Company😀 plans capacity, subject to approval.",body="🌍\n"+excerpt;
        Files.writeString(root.resolve("supplements/body.txt"),body);
        Files.writeString(root.resolve("supplements/time.txt"),"2026-10-21T20:10:30Z");
        basis=mapper.createObjectNode().put("roundId","r").put("eventId","e");
        basis.putArray("evidence").addObject().put("url","https://source.test/news").put("publishedAt","2026-10-21T02:33:00Z");
        node=mapper.createObjectNode().put("status","editorial_sources_not_ai_evaluated").put("linkedAt","2026-10-28T00:00:00Z")
                .put("roundId","r").put("eventId","e").put("companyId","c");
        source=node.putArray("sources").addObject().put("id","s").put("companyId","c").put("title","Authored filing")
                .put("url","https://www.sec.gov/example").put("publishedAt","2026-10-21T20:10:30Z")
                .put("timeBasis","SEC_index_accepted_America_New_York").put("transport","web_tool_extract")
                .put("summary","Plan only").put("limitations","Not a realized outcome").put("historicalVersionVerified",false)
                .put("textPath","supplements/body.txt").put("textSha256",Canonical.sha256(body)).put("excerpt",excerpt)
                .put("start",2).put("end",2+excerpt.codePointCount(0,excerpt.length()));
        source.putObject("timeProof").put("path","supplements/time.txt").put("sha256",Canonical.sha256("2026-10-21T20:10:30Z"))
                .put("contains","2026-10-21T20:10:30Z");
    }
    private BriefingImpacts.ResearchSupplement read() throws Exception {
        return BriefingSupplementalEvidenceReader.read(node,basis,cutoff,root,"c",clock);
    }
    @Test void bindsExactSourcesWithoutAssigningPolarity() throws Exception {
        var result=read();assertEquals(1,result.sources().size());assertFalse(result.sources().getFirst().historicalVersionVerified());
        assertEquals("editorial_sources_not_ai_evaluated",result.status());assertTrue(result.sources().getFirst().excerpt().contains("😀"));
    }
    @Test void rejectsForeignRoundCompanyFutureAndModifiedSource() {
        node.put("roundId","wrong");assertThrows(Exception.class,this::read);node.put("roundId","r");
        source.put("companyId","wrong");assertThrows(Exception.class,this::read);source.put("companyId","c");
        source.put("publishedAt","2026-10-22T01:00:00Z");assertThrows(Exception.class,this::read);
        source.put("publishedAt","2026-10-21T20:10:30Z").put("modifiedAt","2026-10-24T00:00:00Z");assertThrows(Exception.class,this::read);
    }
    @Test void rejectsTamperingForgedQuoteAndPathEscape() throws Exception {
        source.put("start",1);assertThrows(Exception.class,this::read);source.put("start",2);
        source.put("textPath","supplements/../outside");assertThrows(Exception.class,this::read);source.put("textPath","supplements/body.txt");
        Files.writeString(root.resolve("supplements/body.txt"),"tampered");assertThrows(Exception.class,this::read);
    }
    @Test void rejectsIndependentVerificationOrEffectClaimsAndInvalidUrls() {
        source.put("historicalVersionVerified",true);assertThrows(Exception.class,this::read);source.put("historicalVersionVerified",false);
        source.put("effect","positive");assertThrows(Exception.class,this::read);source.remove("effect");
        source.put("url","https://www.sec.gov@evil.test/example");assertThrows(Exception.class,this::read);
    }
    @Test void timeConflictIsAnAnnotationBoundToOriginalEvidence() throws Exception {
        node.putArray("sources");var t=node.putObject("timeCheck").put("status","publisher_time_disagreement")
                .put("summary","Publisher declarations differ").put("limitation","First publication unknown")
                .put("storedPublishedAt","2026-10-21T02:33:00Z").put("distributionPublishedAt","2026-10-21T10:33:00Z")
                .put("storedUrl","https://source.test/news").put("distributionUrl","https://www.globenewswire.com/news");
        assertTrue(read().sources().isEmpty());
        t.put("storedUrl","https://foreign.test/news");assertThrows(Exception.class,this::read);
    }
    @Test void refusesSymlinksAndChangedTimeProof() throws Exception {
        Files.writeString(root.resolve("supplements/time.txt"),"changed");assertThrows(Exception.class,this::read);
        Files.writeString(root.resolve("supplements/time.txt"),"2026-10-21T20:10:30Z");
        Files.move(root.resolve("supplements/body.txt"),root.resolve("target.txt"));
        Files.createSymbolicLink(root.resolve("supplements/body.txt"),root.resolve("target.txt"));assertThrows(Exception.class,this::read);
    }
}
