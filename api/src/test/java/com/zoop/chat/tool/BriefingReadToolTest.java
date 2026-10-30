package com.zoop.chat.tool;

import java.time.Instant;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;

import com.zoop.chat.service.ChatEvidenceAccess;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.document.evidence.service.EvidenceService.Readability;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import static org.junit.jupiter.api.Assertions.*;

/**
 * D-AI-02 Q06 briefing read: one published round through the public briefing read, its issues as items with the evidence
 * readable now, never a round that is not published. Synthetic rounds only.
 */
class BriefingReadToolTest {
    private static final LocalDate DAY = LocalDate.of(2026, 10, 30);
    private static final ChatToolScope SCOPE = new ChatToolScope("job-1", "gv-1", null);
    private static final JsonMapper JSON = JsonMapper.builder().build();

    private final List<String> asked = new ArrayList<>();
    /** ev-1 and ev-2 are readable now, ev-3 is not. */
    private final ChatEvidenceAccess access = (id, version, asOf, trace) -> Set.of("ev-1", "ev-2").contains(id);

    private static JsonNode published() {
        return JSON.readTree("""
                {"id":"br-1","date":"2026-10-30","edition":"morning","status":"published",
                 "publishedAt":"2026-10-30T00:20:00Z","items":[
                  {"eventId":"iss-1","rank":1,"title":"HBM 공급 계약","reason":"관심 기업 두 곳이 함께 연결",
                   "companies":[{"id":"KRX:000660","name":"SK하이닉스"}],"evidenceIds":["ev-1","ev-3"]},
                  {"eventId":"iss-2","rank":2,"title":"EUV 수출 규제","reason":"공급망 영향",
                   "companies":[{"id":"KRX:005930","name":"삼성전자"}],"evidenceIds":["ev-2"]}]}
                """);
    }

    private BriefingReadTool tool(JsonNode response) {
        return new BriefingReadTool((date, edition, trace) -> {
            asked.add(date + "/" + edition);
            return response;
        }, access);
    }

    @Test
    void aPublishedRoundsIssuesAreItemsWithTheEvidenceReadableNow() {
        var output = tool(published()).read(SCOPE, new ChatToolRequest("briefing.read",
                List.of("briefing:2026-10-30:morning"), 20));

        assertEquals(List.of("2026-10-30/morning"), asked);
        assertEquals("briefing:br-1", output.dataVersion());
        assertEquals(List.of("iss-1", "iss-2"), output.items().stream().map(ChatToolItem::id).toList());
        var first = output.items().getFirst();
        assertEquals("briefing_item", first.kind());
        assertEquals("[2026-10-30 출근 브리핑 1위] HBM 공급 계약 — 선정 이유: 관심 기업 두 곳이 함께 연결", first.label());
        assertEquals(List.of("KRX:000660"), first.companyIds());
        assertEquals(List.of("ev-1"), first.evidenceIds(), "evidence not readable now is not passed on");
        assertEquals(List.of("ev-1", "ev-2"), output.evidenceIds());
        assertFalse(output.truncated());
    }

    @Test
    void namedCompaniesKeepOnlyTheirIssuesAndTheLimitCutsEvidence() {
        var mine = tool(published()).read(SCOPE, new ChatToolRequest("briefing.read",
                List.of(ChatBriefingRound.LATEST, "KRX:005930"), 20));
        assertEquals(List.of("null/null"), asked, "the latest round");
        assertEquals(List.of("iss-2"), mine.items().stream().map(ChatToolItem::id).toList());

        var cut = tool(published()).read(SCOPE, new ChatToolRequest("briefing.read", List.of(ChatBriefingRound.LATEST), 1));
        assertEquals(List.of("ev-1"), cut.evidenceIds());
        assertTrue(cut.truncated(), "evidence left unread is a cut, never 'none'");
    }

    @Test
    void aRoundThatIsNotPublishedOrCameAfterTheCutoffHasNothingToRead() {
        for (String status : List.of("not_ready", "generating", "failed", "suspended")) {
            var round = (tools.jackson.databind.node.ObjectNode) published();
            round.put("status", status);
            var output = tool(round).read(SCOPE, new ChatToolRequest("briefing.read", List.of(ChatBriefingRound.LATEST), 20));
            assertTrue(output.items().isEmpty() && output.evidenceIds().isEmpty() && !output.truncated(), status);
        }
        var before = new ChatToolScope("job-1", "gv-1", Instant.parse("2026-10-30T00:00:00Z"));
        var late = tool(published()).read(before, new ChatToolRequest("briefing.read", List.of(ChatBriefingRound.LATEST), 20));
        assertTrue(late.items().isEmpty(), "published after the question's cutoff");
    }

    @Test
    void aReadThatCannotBeMadeIsUnavailableNeverEmpty() {
        var down = new BriefingReadTool((date, edition, trace) -> {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        }, access);
        assertThrows(ChatToolUnavailable.class,
                () -> down.read(SCOPE, new ChatToolRequest("briefing.read", List.of(ChatBriefingRound.LATEST), 20)));
        ChatEvidenceAccess unchecked = new ChatEvidenceAccess() {
            @Override
            public boolean readable(String id, String version, Instant asOf, String trace) {
                return false;
            }

            @Override
            public Readability readability(String id, String version, Instant asOf, String trace) {
                return Readability.UNAVAILABLE;
            }
        };
        assertThrows(ChatToolUnavailable.class, () -> new BriefingReadTool((d, e, t) -> published(), unchecked)
                .read(SCOPE, new ChatToolRequest("briefing.read", List.of(ChatBriefingRound.LATEST), 20)));
        assertThrows(ChatToolUnavailable.class, () -> tool(published()).read(new ChatToolScope("job-1", null, null),
                new ChatToolRequest("briefing.read", List.of(ChatBriefingRound.LATEST), 20)));
        assertThrows(IllegalArgumentException.class, () -> tool(published()).read(SCOPE,
                new ChatToolRequest("briefing.read", List.of("KRX:000660"), 20)), "the first target names the round");
    }

    @Test
    void theRoundIsWhatTheRequirementsWordsName() {
        LocalDate yesterday = DAY.minusDays(1);
        assertEquals(ChatBriefingRound.LATEST, ChatBriefingRound.ref("최근 브리핑 알려줘", null, DAY));
        assertEquals("briefing:2026-10-30:morning", ChatBriefingRound.ref("오늘 아침 브리핑", DAY, DAY));
        assertEquals("briefing:2026-10-30:evening", ChatBriefingRound.ref("퇴근 브리핑에 뭐 나왔어", null, DAY),
                "an edition alone is today's");
        assertEquals("briefing:2026-10-29", ChatBriefingRound.ref("어제 브리핑", yesterday, DAY));
        assertEquals("briefing:2026-10-29", ChatBriefingRound.ref("어제 아침이랑 저녁 브리핑", yesterday, DAY),
                "both editions named: that day's latest");
        assertEquals(new ChatBriefingRound(DAY, "evening"), ChatBriefingRound.parse("briefing:2026-10-30:evening"));
        assertEquals(new ChatBriefingRound(null, null), ChatBriefingRound.parse(ChatBriefingRound.LATEST));
        assertFalse(ChatBriefingRound.isRef("KRX:000660"));
        assertThrows(IllegalArgumentException.class, () -> ChatBriefingRound.parse("briefing:2026-10-30:noon"));
        assertEquals(List.of(ChatBriefingRound.LATEST), ChatCapability.BRIEFING_READ.untargeted());
    }
}
