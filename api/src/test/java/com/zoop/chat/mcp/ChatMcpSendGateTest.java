package com.zoop.chat.mcp;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.zoop.chat.service.ChatCompanyProfiles;
import com.zoop.chat.service.ChatZoopDocs;
import com.zoop.chat.tool.ChatToolItem;
import com.zoop.chat.tool.ChatToolOutput;
import com.zoop.chat.tool.ChatToolPath;
import java.nio.file.Path;
import java.time.Clock;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.Collection;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

/**
 * What of an MCP result may reach the agent model: every item, path and evidence id is kept only when its source's chat grant
 * allows it, and the rest is left out whole with its count. Synthetic outputs and registries only.
 */
class ChatMcpSendGateTest {
    private static final Clock CLOCK = Clock.fixed(ChatMcpGrantsTest.NOW, ZoneOffset.UTC);
    /** ev-a is a granted article's, ev-b an ungranted one's, ev-c cannot be cited now. */
    private static final Map<String, String> PLACED = Map.of("ev-a", "granted-news", "ev-b", "other-news");

    @TempDir
    Path dir;

    private final List<Collection<String>> asked = new ArrayList<>();

    private ChatMcpSendGate gate(String... allowed) {
        Path file = ChatSendGrantsTest.write(dir.resolve("chat-grants.json"), allowed);
        return new ChatMcpSendGate(new ChatSendGrants(file.toString(), ChatSendGrantsTest.RECIPIENT, CLOCK),
                (run, ids) -> {
                    asked.add(List.copyOf(ids));
                    return PLACED;
                });
    }

    private static ChatToolOutput output() {
        return new ChatToolOutput("gv-1", List.of(
                new ChatToolItem("KRX:000660", "company", "SK하이닉스", List.of("KRX:000660"), List.of("ev-a", "ev-b")),
                new ChatToolItem("is-1", "issue", "HBM 공급 확대", List.of("KRX:000660"), List.of("ev-a")),
                new ChatToolItem("ev-a", "evidence", "허용된 기사 제목", List.of(), List.of("ev-a")),
                new ChatToolItem("ev-b", "evidence", "허용되지 않은 기사 제목", List.of(), List.of("ev-b")),
                new ChatToolItem("ev-c", "evidence", "인용할 수 없는 기사 제목", List.of(), List.of("ev-c")),
                new ChatToolItem("doc-1", "zoop_doc", "개인정보 처리방침", List.of(), List.of()),
                new ChatToolItem("x-1", "member_note", "모르는 종류", List.of(), List.of())),
                List.of("ev-a", "ev-b", "ev-c"), false, true,
                List.of(new ChatToolPath("KRX:000660", "KRX:005930", ChatToolPath.FOUND, List.of(
                        new ChatToolPath.Step("e-1", "KRX:000660", "KRX:005930", "SUPPLIES", "supplier",
                                List.of("ev-a", "ev-b"))))));
    }

    @Test
    void everythingGrantedPassesUnchanged() {
        var output = new ChatToolOutput("gv-1", List.of(
                new ChatToolItem("KRX:000660", "company", "SK하이닉스", List.of("KRX:000660"), List.of("ev-a"))),
                List.of("ev-a"), false, false);
        var passed = gate(ChatCompanyProfiles.SOURCE_ID, "granted-news").pass(null, output);
        assertSame(output, passed.output());
        assertEquals(new ChatMcpSendGate.Withheld(0, 0, 0), passed.withheld());
        assertEquals(List.of(List.of("ev-a")), asked);
    }

    @Test
    void whatItsSourceDoesNotAllowIsLeftOutWholeNotSentAsABareId() {
        var passed = gate(ChatCompanyProfiles.SOURCE_ID, ChatMcpSendGate.GRAPH_SOURCE_ID, "granted-news").pass(null, output());
        var out = passed.output();
        assertEquals(List.of("KRX:000660", "is-1", "ev-a"), out.items().stream().map(ChatToolItem::id).toList(),
                "ungranted and uncitable evidence, an ungranted ZOOP document and an unknown kind are left out");
        assertEquals(List.of("ev-a"), out.items().getFirst().evidenceIds());
        assertEquals(List.of("ev-a"), out.evidenceIds());
        assertEquals(List.of("ev-a"), out.paths().getFirst().steps().getFirst().evidenceIds());
        assertEquals("gv-1", out.dataVersion());
        assertTrue(out.nextAllowed());
        assertEquals(new ChatMcpSendGate.Withheld(4, 2, 0), passed.withheld());
        assertEquals(List.of(List.of("ev-a", "ev-b", "ev-c")), asked, "every evidence id is placed once");
    }

    @Test
    void withoutTheGraphsGrantIssuesRelationsAndPathsAreLeftOut() {
        var passed = gate(ChatCompanyProfiles.SOURCE_ID, ChatZoopDocs.SOURCE_ID, "granted-news").pass(null, output());
        assertEquals(List.of("KRX:000660", "ev-a", "doc-1"),
                passed.output().items().stream().map(ChatToolItem::id).toList());
        assertTrue(passed.output().paths().isEmpty());
        assertEquals(1, passed.withheld().paths());
    }

    @Test
    void anOutputWithoutEvidencePlacesNothing() {
        var output = new ChatToolOutput("gv-1", List.of(new ChatToolItem("is-1", "issue", "사건", List.of(), List.of())),
                List.of(), false, false);
        assertEquals(1, gate().pass(null, output).withheld().items());
        assertTrue(asked.isEmpty());
    }

    @Test
    void aRegistryThatCannotBeReadIsNotAnEmptyAllowance() {
        var gate = new ChatMcpSendGate(new ChatSendGrants(dir.resolve("missing.json").toString(),
                ChatSendGrantsTest.RECIPIENT, CLOCK), (run, ids) -> PLACED);
        assertThrows(ChatSendGrants.Unavailable.class, () -> gate.pass(null, output()));
    }
}
