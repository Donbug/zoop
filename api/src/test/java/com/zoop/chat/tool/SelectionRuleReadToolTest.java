package com.zoop.chat.tool;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

import com.zoop.chat.service.ChatEvidenceAccess;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import static org.junit.jupiter.api.Assertions.*;

/**
 * D-AI-02 Q08 selection read: for each named issue visible at the pinned version, its recorded publication, and when the
 * named round picked it, its briefing selection. Nothing about a hidden issue, nothing made up. Synthetic records only.
 */
class SelectionRuleReadToolTest {
    private static final ChatToolScope SCOPE = new ChatToolScope("job-1", "gv-1", null);
    private static final Instant DECIDED = Instant.parse("2026-10-20T05:00:00Z");
    private static final JsonMapper JSON = JsonMapper.builder().build();

    private final Map<String, String> visible = Map.of("iss-1", "HBM 공급 계약", "iss-2", "EUV 수출 규제");
    private final List<String> rounds = new ArrayList<>();
    private final ChatEvidenceAccess access = (id, version, asOf, trace) -> Set.of("ev-1").contains(id);

    private static JsonNode round() {
        return JSON.readTree("""
                {"id":"br-1","date":"2026-10-21","edition":"morning","status":"published",
                 "publishedAt":"2026-10-21T00:20:00Z","items":[
                  {"eventId":"iss-1","rank":1,"title":"HBM 공급 계약","reason":"관심 기업 두 곳이 함께 연결",
                   "companies":[],"evidenceIds":["ev-1","ev-2"]}]}
                """);
    }

    private SelectionRuleReadTool tool(JsonNode round) {
        return new SelectionRuleReadTool((version, asOf, issue) -> Optional.ofNullable(visible.get(issue)),
                (version, issue, title) -> Optional.of(new ChatSelectionRecord.Publication(issue, title, version, 12, 3L,
                        "allow", "admin_review", DECIDED, List.of(new ChatSelectionRecord.Rule("single-source@1",
                        "출처가 기사 1개뿐인 관계 숨기기", "근거 기사 2개 미만인 관계를 숨깁니다.")))),
                (date, edition, trace) -> {
                    rounds.add(date + "/" + edition);
                    return round;
                }, access);
    }

    @Test
    void aVisibleIssueHasItsPublicationAndTheRoundsSelectionWithReadableEvidence() {
        var out = tool(round()).read(SCOPE, new ChatToolRequest("selectionRule.read",
                List.of("briefing:2026-10-21:morning", "iss-1", "iss-2", "iss-hidden"), 20));

        assertEquals("gv-1", out.dataVersion());
        assertEquals(List.of("sel-map:iss-1", "sel-briefing:br-1:iss-1", "sel-map:iss-2"),
                out.items().stream().map(ChatToolItem::id).toList(), "iss-2 was not picked; a hidden issue has nothing");
        assertTrue(out.items().stream().allMatch(i -> "selection_record".equals(i.kind())));
        assertEquals("[지도 gv-1 공개 기록] HBM 공급 계약 — 관리자 검수에서 공개 승인(2026-10-20T05:00:00Z); "
                + "적용된 공개 규칙: 출처가 기사 1개뿐인 관계 숨기기", out.items().getFirst().label());
        assertEquals("[2026-10-21 출근 브리핑 1위 선정 기록] HBM 공급 계약 — 선정 이유: 관심 기업 두 곳이 함께 연결",
                out.items().get(1).label());
        assertEquals(List.of("ev-1"), out.items().get(1).evidenceIds(), "only evidence readable now");
        assertEquals(List.of("ev-1"), out.evidenceIds());
        assertEquals(3, out.selectionRecords().size());
        var selection = assertInstanceOf(ChatSelectionRecord.BriefingSelection.class, out.selectionRecords().get(1));
        assertEquals(1, selection.rank());
        assertEquals(List.of("2026-10-21/morning"), rounds, "the round is read once");
    }

    @Test
    void anUnpublishedRoundPicksNothingAndTheMapRecordStands() {
        var draft = (tools.jackson.databind.node.ObjectNode) round();
        draft.put("status", "generating");
        var out = tool(draft).read(SCOPE, new ChatToolRequest("selectionRule.read",
                List.of(ChatBriefingRound.LATEST, "iss-1"), 20));
        assertEquals(List.of("sel-map:iss-1"), out.items().stream().map(ChatToolItem::id).toList());
    }

    @Test
    void whatCannotBeReadIsUnavailableAndAReadNamesARoundThenIssues() {
        var gone = new SelectionRuleReadTool((v, a, i) -> Optional.of("t"), (v, i, t) -> Optional.empty(),
                (d, e, t) -> round(), access);
        assertThrows(ChatToolUnavailable.class, () -> gone.read(SCOPE,
                new ChatToolRequest("selectionRule.read", List.of(ChatBriefingRound.LATEST, "iss-1"), 20)));
        assertThrows(ChatToolUnavailable.class, () -> tool(round()).read(new ChatToolScope("job-1", null, null),
                new ChatToolRequest("selectionRule.read", List.of(ChatBriefingRound.LATEST, "iss-1"), 20)));
        assertThrows(IllegalArgumentException.class, () -> tool(round()).read(SCOPE,
                new ChatToolRequest("selectionRule.read", List.of(ChatBriefingRound.LATEST), 20)), "no issue");
        assertThrows(IllegalArgumentException.class, () -> tool(round()).read(SCOPE,
                new ChatToolRequest("selectionRule.read", List.of("iss-1"), 20)), "the round comes first");
    }

    @Test
    void aRecordWithoutADecisionSaysNoneWasRecorded() {
        var none = new ChatSelectionRecord.Publication("iss-1", "HBM", "gv-1", 0, null, null, "none", null, List.of());
        assertEquals("[지도 gv-1 공개 기록] HBM — 관리자 검수 결정 기록 없음; 적용된 공개 규칙 없음",
                SelectionRuleReadTool.label(none));
        assertThrows(IllegalArgumentException.class,
                () -> new ChatSelectionRecord.Publication("iss-1", "HBM", "gv-1", 0, null, "allow", "none", DECIDED, List.of()));
    }
}
