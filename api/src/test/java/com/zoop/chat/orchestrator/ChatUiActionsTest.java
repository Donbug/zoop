package com.zoop.chat.orchestrator;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;

import com.zoop.chat.dto.ChatUiAction;
import com.zoop.chat.dto.ChatUiAction.Target;
import com.zoop.chat.dto.GraphTarget;
import com.zoop.chat.tool.ChatToolItem;
import com.zoop.chat.tool.ChatToolPath;
import com.zoop.chat.tool.ChatToolResult;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

/** D-AI-02: what an answer offers to open comes from the reads of its answered requirements, never from the model. */
class ChatUiActionsTest {
    private static final Instant AS_OF = Instant.parse("2026-10-20T00:00:00Z");
    private static final ChatToolItem SAMSUNG = company("KRX:005930", "삼성전자");
    private static final ChatToolItem HYNIX = company("KRX:000660", "SK하이닉스");
    private static final List<GraphTarget> BOTH = List.of(new GraphTarget("KRX:005930", "company"),
            new GraphTarget("KRX:000660", "company"));

    private static ChatToolItem company(String id, String label) {
        return new ChatToolItem(id, "company", label, List.of(), List.of());
    }

    private static ChatToolResult read(String capability, String dataVersion, List<ChatToolItem> items, List<ChatToolPath> paths) {
        return new ChatToolResult("chat-tool/v1", "call-1", capability, dataVersion, items, List.of(), false, false, null, paths);
    }

    private static ChatBranchContext.Branch branch(String id, ChatToolResult... results) {
        return new ChatBranchContext.Branch(id, "요구 " + id, Set.of(ChatQueryType.Q03), false, List.of(results), false);
    }

    @Test
    void aCompanyMustBeATargetOfTheAnswer() {
        var actions = ChatUiActions.of(List.of(branch("r1", read("company.read", "gv-1", List.of(SAMSUNG, HYNIX), List.of()))),
                Set.of("r1"), List.of(new GraphTarget("KRX:000660", "company")), "gv-1", AS_OF);

        assertEquals(1, actions.size());
        var action = actions.getFirst();
        assertEquals(ChatUiAction.OPEN_COMPANY, action.kind());
        assertEquals("기업 상세 · SK하이닉스", action.label());
        assertEquals(Target.company("KRX:000660"), action.target());
        assertEquals(List.of("r1"), action.requirementIds());
    }

    @Test
    void onlyAFoundPathIsOfferedAtTheRunsVersionAndAsOf() {
        var found = new ChatToolPath("KRX:005930", "KRX:000660", "found", List.of(new ChatToolPath.Step("e-1", "KRX:005930",
                "KRX:000660", "SUPPLIES", null, List.of())));
        var cut = new ChatToolPath("KRX:005930", "KRX:035720", "cut", List.of());
        var actions = ChatUiActions.of(List.of(branch("r1", read("graph.path.read", "gv-1", List.of(SAMSUNG, HYNIX),
                List.of(found, cut)))), Set.of("r1"), List.of(), "gv-1", AS_OF);

        assertEquals(1, actions.size());
        assertEquals(ChatUiAction.FOCUS_PATH, actions.getFirst().kind());
        assertEquals("경로 보기 · 삼성전자 → SK하이닉스", actions.getFirst().label());
        assertEquals(Target.path("KRX:005930", "KRX:000660", "gv-1", AS_OF), actions.getFirst().target());
    }

    @Test
    void aBriefingReadOffersTheRoundItReallyFound() {
        var item = new ChatToolItem("iss-1", "briefing_item", "[1위] 제목", List.of(), List.of());
        var actions = ChatUiActions.of(List.of(branch("r1",
                read("briefing.read", "briefing:2026-10-30:evening:br-1", List.of(item), List.of()),
                read("briefing.evidence", "briefing:2026-10-30:evening:br-1", List.of(item), List.of()))),
                Set.of("r1"), List.of(), "gv-1", null);
        assertEquals(Target.briefing("2026-10-30", "evening"), actions.getFirst().target());
        assertEquals("브리핑 열기 · 2026-10-30 퇴근", actions.getFirst().label());

        assertTrue(ChatUiActions.of(List.of(branch("r1", read("briefing.read", "briefing:none", List.of(), List.of()))),
                Set.of("r1"), List.of(), "gv-1", null).isEmpty(), "no round was found");
    }

    @Test
    void aRequirementThatWasNotAnsweredOffersNothing() {
        assertTrue(ChatUiActions.of(List.of(branch("r1", read("company.read", "gv-1", List.of(SAMSUNG), List.of()))),
                Set.of("r2"), BOTH, "gv-1", null).isEmpty());
    }

    @Test
    void theSameTargetIsOfferedOnceForEveryRequirementItServes() {
        var result = read("company.read", "gv-1", List.of(SAMSUNG), List.of());
        var actions = ChatUiActions.of(List.of(branch("r1", result), branch("r2", result)), Set.of("r1", "r2"), BOTH, "gv-1", null);
        assertEquals(1, actions.size());
        assertEquals(List.of("r1", "r2"), actions.getFirst().requirementIds());
    }

    @Test
    void anAnswerOffersAtMostSixInOrderWithTheirOwnIds() {
        List<ChatToolItem> items = new ArrayList<>();
        List<GraphTarget> targets = new ArrayList<>();
        for (int i = 0; i < 8; i++) {
            items.add(company("KRX:00000" + i, "기업" + i));
            targets.add(new GraphTarget("KRX:00000" + i, "company"));
        }
        var actions = ChatUiActions.of(List.of(branch("r1", read("company.read", "gv-1", items, List.of()))), Set.of("r1"),
                targets, "gv-1", null);
        assertEquals(ChatUiActions.MAX, actions.size());
        assertEquals("action-1", actions.getFirst().actionId());
        assertEquals("action-6", actions.getLast().actionId());
    }
}
