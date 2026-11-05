package com.zoop.chat.executor;

import static org.junit.jupiter.api.Assertions.*;

import com.zoop.chat.dto.Citation;
import com.zoop.chat.orchestrator.*;
import com.zoop.chat.repository.ChatJobRow;
import com.zoop.chat.tool.*;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.support.StaticListableBeanFactory;
import tools.jackson.databind.json.JsonMapper;

/** Executes production ownership, dependent retrieval, generation, citation checks, verification and terminal storage offline. */
class ChatResourceBoundaryTest {
    @Test
    void twoRealTwentyOneSecondDependentReadsRetainGenerationAndLongStructuredAnswer() {
        Clock clock = Clock.systemUTC();
        Instant started = clock.instant();
        var store = new MemoryChatStore();
        String evidence = "ev-" + "1".repeat(64);
        String company = "KRX:000660";
        String prose = "공개 근거에서 확인한 공급 계약의 범위와 연결 관계를 차례대로 설명하고 같은 자료의 내용을 함께 살펴봅니다 ".repeat(60) + ".";
        AtomicInteger reads = new AtomicInteger(), generated = new AtomicInteger(), verified = new AtomicInteger();
        ChatModels.Router router = (run, bound, permit) -> new ChatRouteDecision(List.of(
                new ChatRouteDecision.Requirement("r1", "사건의 기업", true, Map.of(ChatQueryType.Q03, .9),
                        Map.of("issue.read", .9), List.of("iss-synthetic"), 0, null),
                new ChatRouteDecision.Requirement("r2", "그 기업의 자료", true, Map.of(ChatQueryType.Q03, .9),
                        Map.of("company.read", .9), List.of(), 0,
                        new ChatRouteDecision.Dependency("r1", "exactly", 1))), null);
        ChatModels.Generator generator = (run, context, permit) -> {
            generated.incrementAndGet();
            assertEquals(64000, permit.resources().path("luna").path("maxOutputTokens").intValue());
            return new ChatGeneratedAnswer(List.of(
                    new ChatGeneratedAnswer.Section("evidence_grounded", prose, List.of("r1"), List.of(evidence)),
                    new ChatGeneratedAnswer.Section("evidence_grounded", "조회한 기업의 공개 자료가 연결되어 있습니다.", List.of("r2"), List.of(evidence))),
                    List.of(), List.of(company));
        };
        ChatModels.Verifier verifier = (run, sections, citations, facts, permit) -> {
            verified.incrementAndGet();
            assertEquals(List.of(evidence), citations.stream().map(Citation::evidenceId).toList());
            return new ChatSemanticVerdicts(sections.stream().map(section -> new ChatSemanticVerdicts.Verdict("supported", "no")).toList());
        };
        List<ChatTool> adapters = List.of(ChatCapability.ISSUE_READ, ChatCapability.COMPANY_READ).stream().map(capability -> (ChatTool) new ChatTool() {
            public ChatCapability capability() { return capability; }
            public ChatToolOutput read(ChatToolScope scope, ChatToolRequest request) {
                try { Thread.sleep(21000); } catch (InterruptedException interrupted) {
                    Thread.currentThread().interrupt(); throw new ChatToolUnavailable("interrupted synthetic read", interrupted);
                }
                reads.incrementAndGet();
                return new ChatToolOutput("gv-synthetic", List.of(new ChatToolItem(
                        capability == ChatCapability.ISSUE_READ ? "iss-synthetic" : company,
                        capability == ChatCapability.ISSUE_READ ? "issue" : "company", "합성 자료", List.of(company), List.of(evidence))),
                        List.of(evidence), false, false);
            }
        }).toList();
        var registry = new ChatToolRegistry(adapters);
        var mapper = JsonMapper.builder().build();
        try (var runner = new ChatToolRunner(registry);
                var engine = new OrchestratedChatEngine(router, generator, verifier, registry, runner,
                        (id, version, asOf, trace) -> Optional.of(new Citation("article", id, "공개 근거입니다.", "art-synthetic", "v1",
                                null, null, 0, 9, "합성 기사", "합성 출처", started.minusSeconds(10), "https://example.test/article")),
                        clock, ChatResourceFixtures.runtime())) {
            String job = "job-resource-dependent";
            store.add(new ChatJobRow(job, "conv-resource", "member-synthetic", 1, "사건의 기업을 찾아 그 기업 자료를 알려줘", "a".repeat(64), started,
                    "{\"items\":[],\"evidenceCount\":0,\"period\":null,\"asOf\":null,\"graphVersion\":\"gv-synthetic\"}",
                    "{\"contextIds\":[],\"evidenceIds\":[],\"evidencePool\":[]}", List.of(), "gv-synthetic", "queued", null, null,
                    null, null, 0, null, null, 0, "[{\"n\":1,\"mode\":\"run\",\"status\":\"queued\"}]", started, started, null));
            var executor = new ChatJobExecutor(store, store, new StaticListableBeanFactory(Map.of("engine", engine)).getBeanProvider(ChatEngine.class),
                    mapper, clock, new NoChatTransactions());
            assertTrue(executor.runOnce());
            var saved = store.job(job);
            assertEquals("completed", saved.row.status(), saved.failure);
            var result = mapper.readTree(saved.result);
            assertEquals(2, reads.get());
            assertEquals(1, generated.get());
            assertEquals(1, verified.get());
            assertEquals(2, result.path("sections").size());
            assertEquals(prose, result.path("sections").get(0).path("text").stringValue());
            assertTrue(result.path("answer").stringValue().codePointCount(0, result.path("answer").stringValue().length()) > 2000);
            assertEquals(evidence, result.path("citations").get(0).path("evidenceId").stringValue());
            var attempt = mapper.readTree(saved.row.attempts()).get(0);
            assertEquals(512000, attempt.path("resourcePolicy").path("maxInputTokens").intValue());
            assertEquals(3, attempt.path("modelResources").size());
            long elapsed = Duration.between(started, clock.instant()).toMillis();
            assertTrue(elapsed >= 42000, "both real read waits ran");
            assertTrue(elapsed < 120000, "dependent reads shared the direct read window");
            System.out.println("resource-boundary: elapsedMs=" + elapsed + ", reads=2, generated=1, verified=1, sections=2, citation=retained, answerChars="
                    + result.path("answer").stringValue().codePointCount(0, result.path("answer").stringValue().length())
                    + ", origin=" + ChatJobResources.class.getProtectionDomain().getCodeSource().getLocation());
        }
    }
}
