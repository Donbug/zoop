package com.zoop.chat.orchestrator;

import java.util.List;
import java.util.Set;
import java.util.stream.IntStream;

import com.zoop.chat.orchestrator.ChatBranchContext.Branch;
import com.zoop.chat.orchestrator.ChatGeneratedAnswer.Section;
import com.zoop.chat.tool.ChatToolItem;
import com.zoop.chat.tool.ChatToolResult;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

/** D-AI-02 layer-1 checks that need no engine: the citation budget and what a general section may say. */
class ChatAnswerCheckTest {
    @Test
    void allSectionsTogetherCiteAtMostTwentyEvidenceIds() {
        var a = branch("a", evidence("a", 11));
        var b = branch("b", evidence("b", 11));
        var tooMany = new ChatGeneratedAnswer(List.of(new Section("evidence_grounded", "A", List.of("a"), evidence("a", 11)),
                new Section("evidence_grounded", "B", List.of("b"), evidence("b", 11))), List.of(), List.of());
        assertEquals("citation_budget", ChatAnswerCheck.check(List.of(a, b), tooMany).failedCheck(),
                "each section is under 20, the answer is not");

        var shared = new ChatGeneratedAnswer(List.of(new Section("evidence_grounded", "A", List.of("a"), evidence("a", 11)),
                new Section("evidence_grounded", "B", List.of("b"), evidence("b", 9))), List.of(), List.of());
        assertNull(ChatAnswerCheck.check(List.of(a, b), shared).failedCheck());
    }

    @Test
    void aGeneralSectionStatesNoCurrentFactAndAnswersOnlyAPureConcept() {
        var concept = new Branch("c", "개념", Set.of(ChatQueryType.Q02), true, List.of(), false);
        for (String text : List.of("HBM 시장은 2026년에 커졌습니다.", "점유율은 50%입니다.", "주가는 $120입니다.",
                "매출은 3조 원입니다.", "10월 21일 발표가 있었습니다.", "최근 공급이 늘었습니다.")) {
            var answer = new ChatGeneratedAnswer(List.of(new Section("general_knowledge", text, List.of("c"), List.of())),
                    List.of(), List.of());
            assertEquals("general_section", ChatAnswerCheck.check(List.of(concept), answer).failedCheck(), text);
        }
        var plain = new ChatGeneratedAnswer(List.of(new Section("general_knowledge",
                "HBM은 메모리 칩을 수직으로 쌓아 대역폭을 높인 메모리입니다.", List.of("c"), List.of())), List.of(), List.of());
        assertNull(ChatAnswerCheck.check(List.of(concept), plain).failedCheck());

        // A lookup requirement that also carries Q02 is not a concept: it cannot be answered from general knowledge.
        var lookup = new Branch("f", "사실", Set.of(ChatQueryType.Q02, ChatQueryType.Q03), false,
                List.of(result(List.of("ev-f"))), false);
        var general = new ChatGeneratedAnswer(List.of(new Section("general_knowledge", "설명", List.of("f"), List.of())),
                List.of(), List.of());
        assertEquals("general_section", ChatAnswerCheck.check(List.of(lookup), general).failedCheck());
    }

    @Test
    void aSplitConceptSectionNamingWhatItsParentReadIsDroppedNotFailed() {
        var parent = branch("f", List.of("ev-f"));
        var split = new Branch("f-c", "요구 f — 개념 설명", Set.of(ChatQueryType.Q02), true, List.of(), false, "f",
                List.of("SK하이닉스", "HBM 공급 확대"));
        for (String text : List.of("SK하이닉스의 HBM은 메모리입니다.", "SK 하이닉스는 메모리 회사입니다.",
                "HBM 공급확대는 수요에서 옵니다.", "HBM 수요는 2026년에 컸습니다.")) {
            var answer = new ChatGeneratedAnswer(List.of(new Section("general_knowledge", text, List.of("f-c"), List.of()),
                    new Section("evidence_grounded", "본문", List.of("f"), List.of("ev-f"))), List.of(), List.of());
            var passed = ChatAnswerCheck.check(List.of(parent, split), answer).passed();
            assertNotNull(passed, text);
            assertEquals(1, passed.sections().size(), text);
            assertEquals(List.of("f-c"), passed.dropped(), text);
            assertEquals(List.of("f-c"), passed.insufficient(), text);
        }
        var plain = new ChatGeneratedAnswer(List.of(new Section("general_knowledge", "HBM은 메모리 반도체입니다.",
                List.of("f-c"), List.of())), List.of("f"), List.of());
        var passed = ChatAnswerCheck.check(List.of(parent, split), plain).passed();
        assertEquals(List.of(), passed.dropped());
        assertEquals(ChatAnswerCheck.GENERAL_NOTICE + " HBM은 메모리 반도체입니다.", passed.sections().getFirst().text());

        // Names are the split requirement's rule only; a router concept is held to the general rules alone.
        var concept = new Branch("c", "개념", Set.of(ChatQueryType.Q02), true, List.of(), false);
        var named = new ChatGeneratedAnswer(List.of(new Section("general_knowledge", "SK하이닉스는 메모리 회사입니다.",
                List.of("c"), List.of())), List.of(), List.of());
        assertNull(ChatAnswerCheck.check(List.of(concept), named).failedCheck());
    }

    @Test
    void aSectionSharedWithAStatedConceptStillChecksTheSplitConceptsNamesAndFailsInsteadOfDropping() {
        var parent = branch("r1", List.of("ev-r1"));
        var split = new Branch("r1-c", "요구 r1 — 개념 설명", Set.of(ChatQueryType.Q02), true, List.of(), false, "r1",
                List.of("SK하이닉스"));
        var stated = new Branch("r2", "메모리 개념", Set.of(ChatQueryType.Q02), true, List.of(), false);
        var named = new ChatGeneratedAnswer(List.of(new Section("general_knowledge",
                "HBM과 DRAM은 메모리입니다. SK하이닉스는 HBM을 주로 엔비디아에 공급합니다.", List.of("r1-c", "r2"), List.of())),
                List.of("r1"), List.of());
        assertEquals("general_names", ChatAnswerCheck.check(List.of(parent, split, stated), named).failedCheck(),
                "the member's own r2 is never dropped silently with the server's addition");

        var factual = new ChatGeneratedAnswer(List.of(new Section("general_knowledge", "HBM 수요는 2026년에 컸습니다.",
                List.of("r1-c", "r2"), List.of())), List.of("r1"), List.of());
        assertEquals("general_section", ChatAnswerCheck.check(List.of(parent, split, stated), factual).failedCheck());

        var plain = new ChatGeneratedAnswer(List.of(new Section("general_knowledge", "HBM과 DRAM은 메모리 반도체입니다.",
                List.of("r1-c", "r2"), List.of())), List.of("r1"), List.of());
        var passed = ChatAnswerCheck.check(List.of(parent, split, stated), plain).passed();
        assertEquals(List.of(), passed.dropped());
        assertEquals(List.of("r1"), passed.insufficient());
    }

    @Test
    void zoopDocumentTextAndPublicEvidenceNeverShareASection() {
        // Q01 + Q03 in one requirement: a policy read and a company read.
        var policy = new ChatToolResult("chat-tool/v1", "tc-1", "zoopPolicy.read", "zoop-docs/policy.privacy@v1",
                List.of(new ChatToolItem("policy.privacy", "zoop_doc", "개인정보 처리방침", List.of(), List.of("ev-doc"))),
                List.of("ev-doc"), false, false, null);
        var both = new Branch("q", "요구 q", Set.of(ChatQueryType.Q01, ChatQueryType.Q03), false,
                List.of(policy, result(List.of("ev-news"))), false);

        var split = new ChatGeneratedAnswer(List.of(
                new Section("zoop_documented", "탈퇴하면 대화 기록이 지워집니다.", List.of("q"), List.of("ev-doc")),
                new Section("evidence_grounded", "SK하이닉스는 HBM을 공급합니다.", List.of("q"), List.of("ev-news"))),
                List.of(), List.of());
        assertNull(ChatAnswerCheck.check(List.of(both), split).failedCheck());

        var newsAsDocument = new ChatGeneratedAnswer(List.of(new Section("zoop_documented", "본문", List.of("q"),
                List.of("ev-news"))), List.of(), List.of());
        assertEquals("document_section", ChatAnswerCheck.check(List.of(both), newsAsDocument).failedCheck());
        var documentAsNews = new ChatGeneratedAnswer(List.of(new Section("evidence_grounded", "본문", List.of("q"),
                List.of("ev-doc"))), List.of(), List.of());
        assertEquals("evidence_section", ChatAnswerCheck.check(List.of(both), documentAsNews).failedCheck());
        var uncited = new ChatGeneratedAnswer(List.of(new Section("zoop_documented", "본문", List.of("q"), List.of())),
                List.of(), List.of());
        assertEquals("document_section", ChatAnswerCheck.check(List.of(both), uncited).failedCheck());
    }

    private static Branch branch(String id, List<String> evidence) {
        return new Branch(id, "요구 " + id, Set.of(ChatQueryType.Q03), false, List.of(result(evidence)), false);
    }

    private static ChatToolResult result(List<String> evidence) {
        return new ChatToolResult("chat-tool/v1", "tc-0", "company.read", "v1",
                List.of(new ChatToolItem("KRX:000660", "company", "SK하이닉스", List.of("KRX:000660"), evidence)), evidence,
                false, false, null);
    }

    private static List<String> evidence(String prefix, int count) {
        return IntStream.range(0, count).mapToObj(i -> "ev-" + prefix + i).toList();
    }
}
