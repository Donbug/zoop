package com.zoop.chat.tool;

import java.util.List;
import java.util.Set;

import com.zoop.chat.service.ChatEvidenceAccess;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import static org.junit.jupiter.api.Assertions.*;

/** D-AI-02 Q06 briefing evidence: the evidence of the issues a published round carried, readable now. Synthetic rounds only. */
class BriefingEvidenceToolTest {
    private static final ChatToolScope SCOPE = new ChatToolScope("job-1", "gv-1", null);
    private static final JsonMapper JSON = JsonMapper.builder().build();
    private static final String ROUND = "briefing:2026-10-30:morning";

    /** ev-3 is not readable now. */
    private final ChatEvidenceAccess access = (id, version, asOf, trace) -> !"ev-3".equals(id);

    private static JsonNode published() {
        return JSON.readTree("""
                {"id":"br-1","date":"2026-10-30","edition":"morning","status":"published",
                 "publishedAt":"2026-10-30T00:20:00Z","items":[
                  {"eventId":"iss-1","rank":1,"title":"HBM 공급 계약","reason":"관심 기업 두 곳이 함께 연결",
                   "companies":[{"id":"KRX:000660","name":"SK하이닉스"}],"evidenceIds":["ev-1","ev-2","ev-3"]},
                  {"eventId":"iss-2","rank":2,"title":"EUV 수출 규제","reason":"공급망 영향",
                   "companies":[{"id":"KRX:005930","name":"삼성전자"}],"evidenceIds":["ev-4"]}]}
                """);
    }

    private BriefingEvidenceTool tool(JsonNode round) {
        return new BriefingEvidenceTool(new BriefingReadTool((date, edition, trace) -> round, access));
    }

    @Test
    void itReadsTheEvidenceOfTheNamedIssueOfTheRoundReadableNow() {
        var output = tool(published()).read(SCOPE, new ChatToolRequest("briefing.evidence", List.of(ROUND, "iss-1"), 20));

        assertEquals(List.of("iss-1"), output.items().stream().map(ChatToolItem::id).toList());
        assertEquals("briefing_item", output.items().getFirst().kind());
        assertEquals(List.of("ev-1", "ev-2"), output.evidenceIds());
        assertEquals("briefing:2026-10-30:morning:br-1", output.dataVersion());
    }

    @Test
    void theLimitIsSpentOnTheNamedIssueNotOnTheIssuesBeforeIt() {
        var output = tool(published()).read(SCOPE, new ChatToolRequest("briefing.evidence", List.of(ROUND, "iss-2"), 1));

        assertEquals(List.of("ev-4"), output.evidenceIds(), "briefing.read would have spent the one on the first issue");
        assertFalse(output.truncated());
    }

    @Test
    void anIssueTheRoundDidNotCarryFindsNothing() {
        var output = tool(published()).read(SCOPE, new ChatToolRequest("briefing.evidence", List.of(ROUND, "iss-9"), 20));

        assertTrue(output.items().isEmpty() && output.evidenceIds().isEmpty());
    }

    @Test
    void withNoIssueNamedItReadsTheRoundAndAnUnpublishedRoundHasNothing() {
        var all = tool(published()).read(SCOPE, new ChatToolRequest("briefing.evidence", List.of(ROUND), 20));
        assertEquals(List.of("ev-1", "ev-2", "ev-4"), all.evidenceIds());

        var round = (tools.jackson.databind.node.ObjectNode) published();
        round.put("status", "suspended");
        assertTrue(tool(round).read(SCOPE, new ChatToolRequest("briefing.evidence", List.of(ROUND, "iss-1"), 20)).items().isEmpty());
    }

    @Test
    void itHonoursTheEvidenceTheMemberNarrowedTo() {
        var output = tool(published()).read(SCOPE, new ChatToolRequest("briefing.evidence", List.of(ROUND, "iss-1"), 20,
                List.of("ev-2"), null));

        assertEquals(List.of("ev-2"), output.evidenceIds());
    }

    @Test
    void aReadNamesOneRoundAndNeedsNoTargetFromTheQuestion() {
        assertThrows(IllegalArgumentException.class, () -> tool(published()).read(SCOPE,
                new ChatToolRequest("briefing.evidence", List.of(ROUND, ChatBriefingRound.LATEST), 20)));
        assertEquals(List.of(ChatBriefingRound.LATEST), ChatCapability.BRIEFING_EVIDENCE.untargeted());
        assertEquals(Set.of(ChatCapability.BRIEFING_EVIDENCE), Set.of(tool(published()).capability()));
    }
}
