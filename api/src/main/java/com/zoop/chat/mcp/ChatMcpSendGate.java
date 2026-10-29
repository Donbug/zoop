package com.zoop.chat.mcp;

import com.zoop.chat.executor.ChatRun;
import com.zoop.chat.service.ChatCompanyProfiles;
import com.zoop.chat.service.ChatZoopDocs;
import com.zoop.chat.tool.ChatToolItem;
import com.zoop.chat.tool.ChatToolOutput;
import com.zoop.chat.tool.ChatToolPath;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.function.Predicate;

/**
 * What of a tool's output may go to the agent model (api/docs/chat-mcp.md 5): each item, path and evidence id only when the
 * chat grant of its source allows sending it to the agent ({@link ChatSendGrants}); the rest is withheld whole, never sent as
 * a bare id, and only the counts say something was. Sources: a company's name is the company catalog's, an issue's title
 * and every path step (ids, relation type and role, no names) are ZOOP's graph's ({@link #GRAPH_SOURCE_ID}), a ZOOP document
 * title ZOOP's documents', and evidence (an evidence item's label is its article's title) the source of its record
 * ({@link ChatMcpSources}). A relation's label is composite, the names of both ends (companies among them) and the
 * relation, so it needs every source it is made of: the graph's and the catalog's. An item of any other kind is withheld.
 */
public final class ChatMcpSendGate {
    /** The chat grant registry's source id of ZOOP's public graph data: issue titles, relations and path steps. */
    public static final String GRAPH_SOURCE_ID = "zoop-graph";

    /** What was left out of a result, by part; all zero when nothing was. */
    public record Withheld(int items, int evidenceIds, int paths) {
        static final Withheld NONE = new Withheld(0, 0, 0);

        public boolean any() {
            return items + evidenceIds + paths > 0;
        }
    }

    /** The output that may be sent and what was left out of it. */
    public record Passed(ChatToolOutput output, Withheld withheld) {
    }

    private final ChatSendGrants grants;
    private final ChatMcpSources sources;

    public ChatMcpSendGate(ChatSendGrants grants, ChatMcpSources sources) {
        this.grants = grants;
        this.sources = sources;
    }

    /**
     * The part of {@code output} that may be sent for {@code run}. Throws {@link ChatSendGrants.Unavailable} when the grant
     * registry cannot be used and {@link com.zoop.chat.tool.ChatToolUnavailable} when evidence cannot be placed.
     */
    public Passed pass(ChatRun run, ChatToolOutput output) {
        Predicate<String> sendable = grants.sendable();
        Set<String> evidence = new LinkedHashSet<>(output.evidenceIds());
        for (ChatToolItem item : output.items()) {
            evidence.addAll(item.evidenceIds());
            if ("evidence".equals(item.kind())) evidence.add(item.id());
        }
        for (ChatToolPath path : output.paths()) {
            for (ChatToolPath.Step step : path.steps()) evidence.addAll(step.evidenceIds());
        }
        Map<String, String> placed = evidence.isEmpty() ? Map.of() : sources.sourcesOf(run, evidence);
        Set<String> allowed = new LinkedHashSet<>();
        for (String id : evidence) {
            if (sendable.test(placed.get(id))) allowed.add(id);
        }
        boolean graph = sendable.test(GRAPH_SOURCE_ID);
        boolean catalog = sendable.test(ChatCompanyProfiles.SOURCE_ID);

        List<ChatToolItem> items = new ArrayList<>();
        for (ChatToolItem item : output.items()) {
            boolean itemAllowed = switch (item.kind()) {
                case "company" -> catalog;
                case "issue" -> graph;
                // "<end> – <end>" (and the relation): company names travel inside it.
                case "edge" -> graph && catalog;
                case "zoop_doc" -> sendable.test(ChatZoopDocs.SOURCE_ID);
                case "evidence" -> allowed.contains(item.id());
                default -> false;
            };
            if (itemAllowed) {
                items.add(new ChatToolItem(item.id(), item.kind(), item.label(), item.companyIds(),
                        item.evidenceIds().stream().filter(allowed::contains).toList()));
            }
        }
        List<ChatToolPath> paths = new ArrayList<>();
        if (graph) {
            for (ChatToolPath path : output.paths()) {
                paths.add(new ChatToolPath(path.fromId(), path.toId(), path.status(), path.steps().stream()
                        .map(s -> new ChatToolPath.Step(s.edgeId(), s.sourceId(), s.targetId(), s.relation(), s.role(),
                                s.evidenceIds().stream().filter(allowed::contains).toList()))
                        .toList()));
            }
        }
        List<String> passedEvidence = output.evidenceIds().stream().filter(allowed::contains).toList();
        var withheld = new Withheld(output.items().size() - items.size(),
                (int) evidence.stream().filter(id -> !allowed.contains(id)).count(), output.paths().size() - paths.size());
        if (!withheld.any()) return new Passed(output, Withheld.NONE);
        return new Passed(new ChatToolOutput(output.dataVersion(), items, passedEvidence, output.truncated(),
                output.nextAllowed(), paths), withheld);
    }
}
