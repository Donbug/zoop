package com.zoop.chat.mcp;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.zoop.chat.service.ChatCompanyProfiles;
import com.zoop.chat.service.ChatZoopDocs;
import com.zoop.chat.tool.ChatCapability;
import com.zoop.chat.tool.ChatToolItem;
import com.zoop.chat.tool.ChatToolOutput;
import com.zoop.chat.tool.ChatToolPath;
import com.zoop.chat.tool.ChatToolRequest;
import com.zoop.chat.tool.ChatToolScope;
import com.zoop.chat.tool.GraphVersionDiffTool;
import com.zoop.graph.read.DisclosureExclusions;
import com.zoop.graph.read.PublicGraphReader;
import com.zoop.graph.snapshot.FixtureGraphSnapshotStore;
import com.zoop.graph.version.GraphVersionRecord;
import com.zoop.graph.version.GraphVersionRepository;
import com.zoop.graph.version.GraphVersionSelector;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Path;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.Collection;
import java.util.List;
import java.util.Map;
import java.util.Optional;
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

    @Test
    void aRelationsLabelCarriesCompanyNamesSoWithoutTheCatalogsGrantItIsLeftOutToo() {
        // The real version diff over the synthetic fixtures: 10-08 added AMD, the AI accelerator issue and its relations to
        // AMD and TSMC, whose labels read "<issue> – AMD (...)".
        var out = versionDiff().read(new ChatToolScope("job-1", "fixture-2026-10-08", null),
                new ChatToolRequest("graph.version.diff", List.of(ChatCapability.WHOLE_GRAPH), 20, null, null));
        assertTrue(out.items().stream().anyMatch(i -> "edge".equals(i.kind()) && i.label().contains("AMD")), out.toString());

        var withoutCatalog = gate(ChatMcpSendGate.GRAPH_SOURCE_ID, "granted-news").pass(null, out);
        assertEquals(List.of("issue"), withoutCatalog.output().items().stream().map(ChatToolItem::kind).distinct().toList());
        assertTrue(withoutCatalog.output().items().stream().noneMatch(i -> i.label().contains("AMD")
                || i.label().contains("TSMC")), "no company name leaves through a relation");
        assertEquals(3, withoutCatalog.withheld().items(), "AMD and both relations");

        var both = gate(ChatMcpSendGate.GRAPH_SOURCE_ID, ChatCompanyProfiles.SOURCE_ID).pass(null, out);
        assertEquals(out.items().size(), both.output().items().size());
    }

    /** {@code graph.version.diff} over the two synthetic graph fixtures, 10-01 public before 10-08. */
    private static GraphVersionDiffTool versionDiff() {
        Instant now = Instant.parse("2026-10-21T03:00:00Z");
        Map<String, GraphVersionRecord> known = Map.of("fixture-2026-10-01", record("fixture-2026-10-01", false),
                "fixture-2026-10-08", record("fixture-2026-10-08", true));
        GraphVersionRepository versions = new GraphVersionRepository() {
            public Optional<GraphVersionRecord> find(String id) { return Optional.ofNullable(known.get(id)); }
            public Optional<GraphVersionRecord> active() { return Optional.of(known.get("fixture-2026-10-08")); }
            public Optional<String> activeVersionIdAt(Instant asOf) {
                if (asOf.isBefore(Instant.parse("2026-10-01T00:00:00Z"))) return Optional.empty();
                return Optional.of(asOf.isBefore(Instant.parse("2026-10-08T00:00:00Z")) ? "fixture-2026-10-01"
                        : "fixture-2026-10-08");
            }
            public boolean everActivated(String id) { return known.containsKey(id); }
            public Optional<Instant> firstActivatedAt(String id) {
                return Optional.ofNullable(known.get(id)).map(r -> Instant.parse(r.id().equals("fixture-2026-10-01")
                        ? "2026-10-01T00:00:00Z" : "2026-10-08T00:00:00Z"));
            }
            public Optional<String> previousVersionId(String id, Instant at) {
                return "fixture-2026-10-08".equals(id) ? Optional.of("fixture-2026-10-01") : Optional.empty();
            }
        };
        Clock clock = Clock.fixed(now, ZoneOffset.UTC);
        var reader = new PublicGraphReader(new GraphVersionSelector(versions, clock),
                new FixtureGraphSnapshotStore(ChatMcpSendGateTest.class.getClassLoader()),
                pinned -> DisclosureExclusions.NONE);
        return new GraphVersionDiffTool(reader, versions, (id, version, asOf, requestId) -> true, clock);
    }

    private static GraphVersionRecord record(String id, boolean active) {
        byte[] bytes;
        try (InputStream in = ChatMcpSendGateTest.class.getClassLoader().getResourceAsStream("graph-fixtures/" + id + ".json")) {
            bytes = in.readAllBytes();
        } catch (IOException e) {
            throw new java.io.UncheckedIOException(e);
        }
        return new GraphVersionRecord(id, 1, "fixture", "artifact-" + id,
                FixtureGraphSnapshotStore.URI_PREFIX + id + ".json", FixtureGraphSnapshotStore.sha256(bytes), active);
    }
}
