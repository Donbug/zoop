package com.zoop.chat.mcp;

import com.zoop.chat.executor.ChatJobExecutor;
import com.zoop.chat.executor.ChatRun;
import com.zoop.chat.executor.ChatRunSuperseded;
import com.zoop.chat.orchestrator.ChatPeriods;
import com.zoop.chat.tool.ChatCapability;
import com.zoop.chat.tool.ChatToolRegistry;
import com.zoop.chat.tool.ChatToolRequest;
import com.zoop.chat.tool.ChatToolResult;
import com.zoop.chat.tool.ChatToolRunner;
import io.modelcontextprotocol.common.McpTransportContext;
import io.modelcontextprotocol.server.McpStatelessServerFeatures.SyncToolSpecification;
import io.modelcontextprotocol.spec.McpSchema;
import java.nio.charset.StandardCharsets;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.Set;
import tools.jackson.databind.ObjectMapper;

/**
 * The chat read tools as MCP tools: every capability bound in {@link ChatToolRegistry} except the member scope read, which
 * the server runs itself before a model is involved (Q07). A call is executed for the job attempt its grant names, through
 * the same {@link ChatToolRunner} and {@code chat_tool_calls} ledger as the server's own plans, so the same per-attempt call
 * limit, timeouts and adapter checks apply.
 *
 * <p>A model chooses only the targets and a result limit. Everything else comes from the job: the pinned graph version and
 * asOf, the evidence the member narrowed the selection to, the compared period of a graph diff and the fixed ZOOP documents
 * of a policy read. A refused or failed call is a tool error result with a code ({@code isError}), never an empty success.
 */
public final class ChatMcpTools {
    /** The {@link McpTransportContext} key of the verified grant (set by {@link ChatMcpAccessFilter}). */
    public static final String GRANT = "zoop.chat.mcp.grant";
    /** The ledger's plan revision of MCP calls: a run that hands tools to a model has no server plan of its own. */
    static final int PLAN_REVISION = 1;
    static final String VIA = "mcp";
    /** Largest serialized result a call returns; a larger one is refused instead of being cut. */
    static final int MAX_RESULT_BYTES = 256 * 1024;

    static final String NOT_GRANTED = "tool_not_granted";
    static final String RUN_NOT_ACTIVE = "run_not_active";
    static final String GRANT_MISMATCH = "grant_mismatch";
    static final String INVALID_ARGUMENTS = "invalid_arguments";
    static final String BUDGET_EXHAUSTED = "tool_budget_exhausted";
    static final String RESULT_TOO_LARGE = "result_too_large";

    private final ChatToolRegistry registry;
    private final ChatToolRunner runner;
    private final ChatJobExecutor executor;
    private final ObjectMapper mapper;

    public ChatMcpTools(ChatToolRegistry registry, ChatToolRunner runner, ChatJobExecutor executor, ObjectMapper mapper) {
        this.registry = registry;
        this.runner = runner;
        this.executor = executor;
        this.mapper = mapper;
    }

    /** The MCP tool name of a capability: its id with dots as underscores (model tool names allow no dots). */
    public static String name(ChatCapability capability) {
        return capability.id().replace('.', '_');
    }

    static Optional<ChatCapability> capability(String name) {
        return name == null ? Optional.empty()
                : java.util.Arrays.stream(ChatCapability.values()).filter(c -> name(c).equals(name)).findFirst();
    }

    /** The capabilities exposed as MCP tools, in declaration order. */
    public List<ChatCapability> exposed() {
        Set<String> bound = registry.bound();
        return java.util.Arrays.stream(ChatCapability.values())
                .filter(c -> c != ChatCapability.PORTFOLIO_SCOPE_READ && bound.contains(c.id())).toList();
    }

    public List<SyncToolSpecification> specifications() {
        return exposed().stream().map(capability -> SyncToolSpecification.builder().tool(tool(capability))
                .callHandler((context, request) -> call(context, request)).build()).toList();
    }

    /** Whether the context's grant lists the tool; {@code tools/list} shows only these. */
    public static boolean visible(McpTransportContext context, McpSchema.Tool tool) {
        return context.get(GRANT) instanceof ChatMcpGrant grant
                && capability(tool.name()).filter(grant::allows).isPresent();
    }

    McpSchema.CallToolResult call(McpTransportContext context, McpSchema.CallToolRequest request) {
        if (!(context.get(GRANT) instanceof ChatMcpGrant grant)) return refused(NOT_GRANTED);
        Optional<ChatCapability> capability = capability(request.name()).filter(exposed()::contains);
        if (capability.isEmpty() || !grant.allows(capability.get())) return refused(NOT_GRANTED);
        var attached = executor.attach(grant.jobId(), grant.attemptNo());
        if (attached.isEmpty()) return refused(RUN_NOT_ACTIVE);
        ChatRun run = attached.get().run();
        if (!Objects.equals(run.graphVersionId(), grant.graphVersionId())
                || !Objects.equals(run.context().asOf(), grant.asOf())) {
            return refused(GRANT_MISMATCH);
        }
        ChatToolRequest call;
        try {
            call = request(run, capability.get(), request.arguments());
        } catch (IllegalArgumentException invalid) {
            return refused(INVALID_ARGUMENTS);
        }
        ChatToolResult result;
        try {
            result = runner.runStage(run, attached.get().control(), PLAN_REVISION, List.of(call), VIA).getFirst();
        } catch (ChatRunSuperseded ended) {
            return refused(RUN_NOT_ACTIVE);
        } catch (IllegalArgumentException overLimit) {
            // The attempt already reserved every call it may make.
            return refused(BUDGET_EXHAUSTED);
        }
        Map<String, Object> structured = structured(result);
        String text = mapper.writeValueAsString(structured);
        if (text.getBytes(StandardCharsets.UTF_8).length > MAX_RESULT_BYTES) return refused(RESULT_TOO_LARGE);
        return McpSchema.CallToolResult.builder().structuredContent(structured).addTextContent(text)
                .isError(!result.succeeded()).build();
    }

    /**
     * The call a model's arguments make: {@code targets} (1 to 5 distinct ids) and an optional {@code limit} (1 to 20), and
     * nothing else. A fixed-document read takes no targets; a graph diff without targets reads the whole public graph.
     */
    static ChatToolRequest request(ChatRun run, ChatCapability capability, Map<String, Object> arguments) {
        Map<String, Object> args = arguments == null ? Map.of() : arguments;
        boolean fixed = !capability.documents().isEmpty();
        Set<String> allowed = fixed ? Set.of("limit") : Set.of("targets", "limit");
        if (!allowed.containsAll(args.keySet())) throw new IllegalArgumentException("unknown argument");
        List<String> targets;
        if (fixed) {
            targets = capability.documents();
        } else if (args.get("targets") instanceof List<?> given) {
            targets = new ArrayList<>();
            for (Object target : given) {
                if (!(target instanceof String id) || id.isBlank() || id.length() > 128) {
                    throw new IllegalArgumentException("targets are ids");
                }
                targets.add(id);
            }
            if (new HashSet<>(targets).size() != targets.size()) throw new IllegalArgumentException("repeated target");
        } else if (args.containsKey("targets")) {
            throw new IllegalArgumentException("targets are a list");
        } else {
            targets = capability.untargeted();
        }
        int limit = ChatToolRequest.MAX_LIMIT;
        if (args.containsKey("limit")) {
            if (!(args.get("limit") instanceof Number n) || n.doubleValue() != Math.rint(n.doubleValue())) {
                throw new IllegalArgumentException("limit is an integer");
            }
            limit = n.intValue();
        }
        var selection = run.selection();
        List<String> scope = fixed || selection.evidenceIds().isEmpty() ? null : selection.evidencePool();
        var period = run.context().period();
        var since = capability != ChatCapability.GRAPH_VERSION_DIFF || period == null ? null
                : new ChatPeriods.Period(LocalDate.parse(period.start()), LocalDate.parse(period.end()), null)
                        .startInstant();
        // ChatToolRequest checks the target count (1 to 5) and the limit range.
        return new ChatToolRequest(capability.id(), targets, limit, scope, since);
    }

    private static McpSchema.Tool tool(ChatCapability capability) {
        boolean fixed = !capability.documents().isEmpty();
        Map<String, Object> properties = new LinkedHashMap<>();
        if (!fixed) {
            properties.put("targets", Map.of("type", "array", "minItems", 1, "maxItems", ChatToolRequest.MAX_TARGETS,
                    "uniqueItems", true, "items", Map.of("type", "string", "minLength", 1, "maxLength", 128),
                    "description", "읽을 대상 ID(기업·사건·근거). 조회 결과에 나온 ID만 사용"));
        }
        properties.put("limit", Map.of("type", "integer", "minimum", 1, "maximum", ChatToolRequest.MAX_LIMIT,
                "description", "전달받을 근거 수 상한(기본 " + ChatToolRequest.MAX_LIMIT + ")"));
        Map<String, Object> schema = new LinkedHashMap<>();
        schema.put("type", "object");
        schema.put("properties", properties);
        schema.put("required", fixed || !capability.untargeted().isEmpty() ? List.of() : List.of("targets"));
        schema.put("additionalProperties", false);
        return McpSchema.Tool.builder(name(capability), schema).title(capability.id())
                .description(capability.description())
                .annotations(new McpSchema.ToolAnnotations(capability.id(), true, false, true, false, null))
                .build();
    }

    private static Map<String, Object> structured(ChatToolResult result) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("schemaVersion", result.schemaVersion());
        out.put("toolCallId", result.toolCallId());
        out.put("capabilityId", result.capabilityId());
        out.put("dataVersion", result.dataVersion());
        out.put("items", result.items());
        out.put("evidenceIds", result.evidenceIds());
        out.put("truncated", result.truncated());
        out.put("nextAllowed", result.nextAllowed());
        out.put("error", result.error());
        if (!result.paths().isEmpty()) out.put("paths", result.paths());
        return out;
    }

    private static McpSchema.CallToolResult refused(String code) {
        Map<String, Object> error = new LinkedHashMap<>();
        error.put("error", code);
        return McpSchema.CallToolResult.builder().structuredContent(error).addTextContent("{\"error\":\"" + code + "\"}")
                .isError(true).build();
    }
}
