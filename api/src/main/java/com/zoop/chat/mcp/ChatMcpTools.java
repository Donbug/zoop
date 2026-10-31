package com.zoop.chat.mcp;

import com.zoop.chat.executor.ChatJobExecutor;
import com.zoop.chat.executor.ChatRun;
import com.zoop.chat.executor.ChatRunControl;
import com.zoop.chat.executor.ChatRunSuperseded;
import com.zoop.chat.executor.ChatWebBudgetExhausted;
import com.zoop.chat.repository.ChatKeptToolResult;
import com.zoop.chat.orchestrator.ChatPeriods;
import com.zoop.chat.tool.ChatCapability;
import com.zoop.chat.tool.ChatToolItem;
import com.zoop.chat.tool.ChatToolOutput;
import com.zoop.chat.tool.ChatToolPath;
import com.zoop.chat.tool.ChatToolRegistry;
import com.zoop.chat.tool.ChatToolRequest;
import com.zoop.chat.tool.ChatToolResult;
import com.zoop.chat.tool.ChatToolRunner;
import com.zoop.chat.tool.ChatToolUnavailable;
import com.zoop.chat.tool.ChatWebQueryPolicy;
import com.zoop.chat.tool.ChatWebResult;
import com.zoop.chat.tool.ChatWebSearchTool;
import io.modelcontextprotocol.common.McpTransportContext;
import io.modelcontextprotocol.server.McpStatelessServerFeatures.SyncToolSpecification;
import io.modelcontextprotocol.spec.McpSchema;
import java.time.Duration;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.Set;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * The chat read tools as MCP tools: every capability bound in {@link ChatToolRegistry} except the member scope read, which
 * the server runs itself before a model is involved (Q07). A call is executed for the job attempt its grant names, through
 * the same {@link ChatToolRunner} and {@code chat_tool_calls} ledger as the server's own plans, so the same per-attempt call
 * limit, timeouts and adapter checks apply. A grant only opens the door: a call runs only when it is exactly a call the
 * server approved ahead ({@link #approve}), once.
 *
 * <p>A model chooses only the targets and a result limit. Everything else comes from the job: the pinned graph version and
 * asOf, the evidence the member narrowed the selection to, the compared period of a graph diff and the fixed ZOOP documents
 * of a policy read. A refused or failed call is a tool error result with a code ({@code isError}), never an empty success.
 *
 * <p>A result goes from here to the model provider directly, so before it is recorded and returned it is narrowed to what
 * the chat grants allow sending to the agent ({@link ChatMcpSendGate}); a result whose grants cannot be checked is refused
 * ({@link #SEND_GRANTS_UNAVAILABLE}), never returned unchecked.
 */
public final class ChatMcpTools {
    /** The {@link McpTransportContext} key of the verified grant (set by {@link ChatMcpAccessFilter}). */
    public static final String GRANT = "zoop.chat.mcp.grant";
    /** The ledger's plan revision of MCP calls: a run that hands tools to a model has no server plan of its own. */
    static final int PLAN_REVISION = 1;
    static final String VIA = "mcp";
    /** The argument naming the requirements a call serves: decided at its approval, no part of what it reads. */
    static final String REQUIREMENT_IDS = "requirementIds";
    /**
     * Largest result a call returns; a larger one is refused instead of being cut. Checked early on the serialized output,
     * and again as stored when it is recorded ({@link ChatRunControl#toolCallFinished}).
     */
    static final int MAX_RESULT_BYTES = ChatRunControl.MAX_CALL_RESULT_BYTES;

    /** The longest wait for an identical request being read: a tool stage (10 s) and its record (2 s). */
    static final Duration SINGLE_FLIGHT_WAIT = Duration.ofSeconds(12);
    private static final TypeReference<List<ChatToolItem>> ITEMS = new TypeReference<>() { };
    private static final TypeReference<List<ChatToolPath>> PATHS = new TypeReference<>() { };
    private static final TypeReference<List<String>> STRINGS = new TypeReference<>() { };
    private static final TypeReference<List<ChatWebResult>> WEB = new TypeReference<>() { };

    private static final Map<String, Object> REQUIREMENT_IDS_SCHEMA = Map.of("type", "array", "minItems", 1, "uniqueItems", true,
            "items", Map.of("type", "string", "minLength", 1, "maxLength", 32),
            "description", "이 호출이 답하는 요구의 requirementId. 구간은 자기 요구를 지목한 호출의 결과만 인용할 수 있음");

    /** Room for the result envelope's own fields beyond the adapter output. */
    private static final int ENVELOPE_BYTES = 1024;

    static final String NOT_GRANTED = "tool_not_granted";
    static final String NOT_APPROVED = "call_not_approved";
    static final String RUN_NOT_ACTIVE = "run_not_active";
    static final String GRANT_MISMATCH = "grant_mismatch";
    static final String INVALID_ARGUMENTS = "invalid_arguments";
    static final String BUDGET_EXHAUSTED = "tool_budget_exhausted";
    /** The job's web searches, or the member's or project's for the day, are used up (web search design 3). */
    static final String WEB_BUDGET_EXHAUSTED = "web_budget_exhausted";
    static final String RESULT_TOO_LARGE = ChatRunControl.RESULT_TOO_LARGE;
    static final String SEND_GRANTS_UNAVAILABLE = "send_grants_unavailable";
    /** What a result says when part of it was withheld for want of a send grant. */
    static final String SOURCE_GRANT_DENIED = "source_grant_denied";

    private final ChatToolRegistry registry;
    private final ChatToolRunner runner;
    private final ChatJobExecutor executor;
    private final ChatMcpSendGate gate;
    private final ObjectMapper mapper;
    /** Identical requests being read now, by attempt, capability and input digest (this instance only). */
    private final Map<String, CompletableFuture<Void>> flights = new ConcurrentHashMap<>();

    public ChatMcpTools(ChatToolRegistry registry, ChatToolRunner runner, ChatJobExecutor executor, ChatMcpSendGate gate,
            ObjectMapper mapper) {
        this.registry = registry;
        this.runner = runner;
        this.gate = gate;
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

    /**
     * The capabilities exposed as MCP tools, in declaration order: every planned read but the member scope, and the web
     * search when it is registered. The web search is never planned by the server ({@link ChatToolRegistry#bound}); on the
     * agent path Luna may ask for it and the server decides each call ({@link ChatMcpAgent}).
     */
    public List<ChatCapability> exposed() {
        Set<String> bound = registry.bound();
        boolean web = registry.bind(ChatCapability.WEB_SEARCH.id()).isPresent();
        return java.util.Arrays.stream(ChatCapability.values())
                // A briefing read's round comes from the requirement's words, which the agent's arguments cannot carry.
                // A selection read's round comes from those words too, and its records are not sent to the agent.
                .filter(c -> c != ChatCapability.PORTFOLIO_SCOPE_READ && c != ChatCapability.BRIEFING_READ
                        && c != ChatCapability.SELECTION_RULE_READ
                        && bound.contains(c.id())
                        || c == ChatCapability.WEB_SEARCH && web).toList();
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

    /** The outcome of an approval: the reserved call's id, or the code it was refused with. */
    public record Approval(String toolCallId, String refused) {
        public boolean approved() {
            return toolCallId != null;
        }
    }

    /**
     * Approves one exact call for the attached run (the server's decision on a model's {@code mcp_approval_request}): the
     * named MCP tool with these arguments, completed by what the server injects. Approving reserves the call in
     * {@code chat_tool_calls}, so it counts against the attempt's call limit at once; {@code /mcp} then runs only a call
     * that matches a reservation, and each reservation only once. A reservation never called is closed as
     * {@code cancelled} with the job. {@code requirementIds} go on the call's record; they do not change what is read.
     */
    public Approval approve(ChatJobExecutor.Attached attached, String toolName, Map<String, Object> arguments,
            List<String> requirementIds) {
        Optional<ChatCapability> capability = capability(toolName).filter(exposed()::contains);
        if (capability.isEmpty()) return new Approval(null, NOT_GRANTED);
        ChatRun run = attached.run();
        ChatToolRequest call;
        try {
            call = request(run, capability.get(), arguments);
        } catch (IllegalArgumentException invalid) {
            return new Approval(null, INVALID_ARGUMENTS);
        }
        var reservation = runner.reservation(run, call, VIA, requirementIds);
        try {
            return new Approval(attached.control().reserveToolCalls(PLAN_REVISION, List.of(reservation)).getFirst(),
                    null);
        } catch (ChatRunSuperseded ended) {
            return new Approval(null, RUN_NOT_ACTIVE);
        } catch (ChatWebBudgetExhausted spent) {
            return new Approval(null, WEB_BUDGET_EXHAUSTED);
        } catch (IllegalArgumentException overLimit) {
            // The attempt already reserved every call it may make.
            return new Approval(null, BUDGET_EXHAUSTED);
        }
    }

    McpSchema.CallToolResult call(McpTransportContext context, McpSchema.CallToolRequest request) {
        if (!(context.get(GRANT) instanceof ChatMcpGrant grant)) return refused(NOT_GRANTED);
        Optional<ChatCapability> capability = capability(request.name()).filter(exposed()::contains);
        if (capability.isEmpty() || !grant.allows(capability.get())) return refused(NOT_GRANTED);
        var attached = executor.attach(grant.jobId(), grant.attemptNo());
        if (attached.isEmpty()) return refused(RUN_NOT_ACTIVE);
        ChatRun run = attached.get().run();
        if (!Objects.equals(run.graphVersionId(), grant.graphVersionId())
                || !Objects.equals(run.context().asOf(), grant.asOf())
                || !grant.scope().equals(ChatMcpGrants.scope(run))) {
            return refused(GRANT_MISMATCH);
        }
        ChatToolRequest call;
        try {
            call = request(run, capability.get(), request.arguments());
        } catch (IllegalArgumentException invalid) {
            return refused(INVALID_ARGUMENTS);
        }
        // Only the exact call the server approved runs: same tool, same canonical request (targets, limit and everything
        // injected), reserved for this attempt and not started yet.
        String digest = runner.reservation(run, call, VIA).inputDigest();
        var control = attached.get().control();
        // The approval this request uses is picked and started in one step: requests arriving together each take their
        // own, and none is left behind for one that took another's.
        Optional<String> approved;
        try {
            approved = control.claimToolCall(call.capabilityId(), digest);
        } catch (ChatRunSuperseded ended) {
            return refused(RUN_NOT_ACTIVE);
        }
        if (approved.isEmpty()) return refused(NOT_APPROVED);
        var delivery = new Delivery(run);
        ChatToolResult result;
        // One read per identical request of the attempt (MCP actions contract 3.3): a request that arrives while the same
        // one is being read waits for it, and then, like a later repeat, reuses what it kept.
        String flight = run.jobId() + "/" + run.attemptNo() + "/" + call.capabilityId() + "/" + digest;
        CompletableFuture<Void> mine = new CompletableFuture<>();
        CompletableFuture<Void> earlier = flights.putIfAbsent(flight, mine);
        try {
            if (earlier != null) awaitEarlier(earlier, control.remaining());
            Optional<ChatKeptToolResult> reused = executor.keptToolResult(run.jobId(), run.attemptNo(),
                    call.capabilityId(), digest);
            if (reused.isPresent()) {
                ChatToolResult kept = kept(mapper, reused.get());
                delivery.cachedFrom = kept.toolCallId();
                result = runner.runCached(run, control, approved.get(), call, new ChatToolOutput(
                        kept.dataVersion(), kept.items(), kept.evidenceIds(), Boolean.TRUE.equals(kept.truncated()),
                        Boolean.TRUE.equals(kept.nextAllowed()), kept.paths(), kept.webResults()), delivery);
            } else {
                result = runner.runClaimed(run, control, approved.get(), call, delivery);
            }
        } catch (ChatRunSuperseded lost) {
            return refused(RUN_NOT_ACTIVE);
        } finally {
            if (earlier == null) {
                flights.remove(flight, mine);
                mine.complete(null);
            }
        }
        if (delivery.refusal != null && delivery.refusal.equals(result.error())) return refused(delivery.refusal);
        // Refused when recorded: over a result's or the job's limit as the column stores it.
        if (ChatRunControl.RESULT_TOO_LARGE.equals(result.error())
                || ChatRunControl.RESULTS_OVER_BUDGET.equals(result.error())) {
            return refused(result.error());
        }
        Map<String, Object> structured = structured(result, delivery.withheld, delivery.cachedFrom);
        return McpSchema.CallToolResult.builder().structuredContent(structured)
                .addTextContent(mapper.writeValueAsString(structured)).isError(!result.succeeded()).build();
    }

    /**
     * What one usable MCP read does before it is recorded: it is narrowed to what the send grants allow
     * ({@link ChatMcpSendGate}), refused as {@link #SEND_GRANTS_UNAVAILABLE} when that cannot be decided and as
     * {@link #RESULT_TOO_LARGE} over {@link #MAX_RESULT_BYTES}; otherwise the success keeps exactly the envelope the model
     * receives, so the server checks the final answer against it.
     */
    private final class Delivery implements ChatToolRunner.Delivery {
        private final ChatRun run;
        // pass() runs on the read's thread, the rest while the call is recorded.
        private volatile String refusal;
        private volatile ChatMcpSendGate.Withheld withheld = ChatMcpSendGate.Withheld.NONE;
        /** The call whose kept result this one reuses; null for a read. */
        private volatile String cachedFrom;

        Delivery(ChatRun run) {
            this.run = run;
        }

        @Override
        public ChatToolOutput pass(ChatToolOutput output) {
            try {
                var passed = gate.pass(run, output);
                withheld = passed.withheld();
                return passed.output();
            } catch (ChatSendGrants.Unavailable | ChatToolUnavailable unchecked) {
                refusal = SEND_GRANTS_UNAVAILABLE;
                return output;
            }
        }

        @Override
        public String refuse(ChatToolOutput output) {
            if (refusal != null) return refusal;
            // The envelope adds a few short fields (ids, versions, flags) to the output's own serialization.
            int bytes = mapper.writeValueAsBytes(output).length + ENVELOPE_BYTES;
            if (bytes > MAX_RESULT_BYTES) refusal = RESULT_TOO_LARGE;
            return refusal;
        }

        @Override
        public String keep(ChatToolResult result) {
            return mapper.writeValueAsString(structured(result, withheld, cachedFrom));
        }
    }

    /**
     * The call a model's arguments make: {@code targets} (1 to 5 distinct ids) and an optional {@code limit} (1 to 20), and
     * nothing else. A fixed-document read takes no targets; a graph diff without targets reads the whole public graph. A
     * web search takes exactly one query that {@link ChatWebQueryPolicy} lets out, normalized as it is sent, and at most
     * {@link ChatWebSearchTool#MAX_HITS} hits. {@link #REQUIREMENT_IDS} is set aside: the approval already took it.
     */
    static ChatToolRequest request(ChatRun run, ChatCapability capability, Map<String, Object> arguments) {
        Map<String, Object> args = arguments == null ? new LinkedHashMap<>() : new LinkedHashMap<>(arguments);
        args.remove(REQUIREMENT_IDS);
        if (capability.web()) return webRequest(args);
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
        var period = run.period();
        var since = capability != ChatCapability.GRAPH_VERSION_DIFF || period == null ? null
                : new ChatPeriods.Period(LocalDate.parse(period.start()), LocalDate.parse(period.end()), null)
                        .startInstant();
        // ChatToolRequest checks the target count (1 to 5) and the limit range.
        return new ChatToolRequest(capability.id(), targets, limit, scope, since);
    }

    private static ChatToolRequest webRequest(Map<String, Object> args) {
        if (!Set.of("targets", "limit").containsAll(args.keySet())) throw new IllegalArgumentException("unknown argument");
        if (!(args.get("targets") instanceof List<?> given) || given.size() != 1 || !(given.getFirst() instanceof String q)) {
            throw new IllegalArgumentException("a web search takes exactly one query");
        }
        String query = ChatWebQueryPolicy.checked(q).orElseThrow(() -> new IllegalArgumentException("query may not leave"));
        int limit = ChatWebSearchTool.MAX_HITS;
        if (args.containsKey("limit")) {
            if (!(args.get("limit") instanceof Number n) || n.doubleValue() != Math.rint(n.doubleValue())
                    || n.intValue() < 1 || n.intValue() > ChatWebSearchTool.MAX_HITS) {
                throw new IllegalArgumentException("limit is 1 to " + ChatWebSearchTool.MAX_HITS);
            }
            limit = n.intValue();
        }
        // No evidence scope and no period: a web hit is no ZOOP evidence, and the query names its own period.
        return new ChatToolRequest(ChatCapability.WEB_SEARCH.id(), List.of(query), limit);
    }

    private static McpSchema.Tool tool(ChatCapability capability) {
        if (capability.web()) return webTool();
        boolean fixed = !capability.documents().isEmpty();
        Map<String, Object> properties = new LinkedHashMap<>();
        if (!fixed) {
            properties.put("targets", Map.of("type", "array", "minItems", 1, "maxItems", ChatToolRequest.MAX_TARGETS,
                    "uniqueItems", true, "items", Map.of("type", "string", "minLength", 1, "maxLength", 128),
                    "description", "읽을 대상 ID(기업·사건·근거). 조회 결과에 나온 ID만 사용"));
        }
        properties.put("limit", Map.of("type", "integer", "minimum", 1, "maximum", ChatToolRequest.MAX_LIMIT,
                "description", "전달받을 근거 수 상한(기본 " + ChatToolRequest.MAX_LIMIT + ")"));
        properties.put(REQUIREMENT_IDS, REQUIREMENT_IDS_SCHEMA);
        Map<String, Object> schema = new LinkedHashMap<>();
        schema.put("type", "object");
        schema.put("properties", properties);
        schema.put("required", fixed || !capability.untargeted().isEmpty() ? List.of(REQUIREMENT_IDS)
                : List.of("targets", REQUIREMENT_IDS));
        schema.put("additionalProperties", false);
        return McpSchema.Tool.builder(name(capability), schema).title(capability.id())
                .description(capability.description())
                .annotations(new McpSchema.ToolAnnotations(capability.id(), true, false, true, false, null))
                .build();
    }

    private static McpSchema.Tool webTool() {
        Map<String, Object> properties = new LinkedHashMap<>();
        properties.put("targets", Map.of("type", "array", "minItems", 1, "maxItems", 1, "items",
                Map.of("type", "string", "minLength", 2, "maxLength", ChatWebQueryPolicy.MAX_LENGTH),
                "description", "검색어 하나. 공개 기업명·공개 키워드·기간만 쓰고 질문 원문이나 회원 정보(보유·수익률 등)는 쓰지 않음"));
        properties.put("limit", Map.of("type", "integer", "minimum", 1, "maximum", ChatWebSearchTool.MAX_HITS,
                "description", "받을 결과 수 상한(기본 " + ChatWebSearchTool.MAX_HITS + ")"));
        properties.put(REQUIREMENT_IDS, REQUIREMENT_IDS_SCHEMA);
        Map<String, Object> schema = new LinkedHashMap<>();
        schema.put("type", "object");
        schema.put("properties", properties);
        schema.put("required", List.of("targets", REQUIREMENT_IDS));
        schema.put("additionalProperties", false);
        var capability = ChatCapability.WEB_SEARCH;
        return McpSchema.Tool.builder(name(capability), schema).title(capability.id())
                .description(capability.description() + ". 줍의 조회로 답할 수 없는 부분에만 쓰고, 결과는 줍의 근거가 아님")
                .annotations(new McpSchema.ToolAnnotations(capability.id(), true, false, true, true, null))
                .build();
    }

    /**
     * The envelope the model receives. When the send gate left something out, {@code withheld} says how much of each part and
     * why, so a short result is never read as everything there is.
     */
    private static Map<String, Object> structured(ChatToolResult result, ChatMcpSendGate.Withheld withheld,
            String cachedFrom) {
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
        if (!result.webResults().isEmpty()) out.put("webResults", result.webResults());
        // A reuse says which call read it: the same data, not a second lookup.
        if (result.succeeded() && cachedFrom != null) out.put("cachedFrom", cachedFrom);
        if (result.succeeded() && withheld.any()) {
            Map<String, Object> left = new LinkedHashMap<>();
            left.put("reason", SOURCE_GRANT_DENIED);
            left.put("items", withheld.items());
            left.put("evidenceIds", withheld.evidenceIds());
            left.put("paths", withheld.paths());
            if (withheld.webResults() > 0) left.put("webResults", withheld.webResults());
            out.put("withheld", left);
        }
        return out;
    }

    /**
     * Waits for an identical request this instance is reading, at most as long as a read and its record can take and never
     * past the run's deadline. Past that the request reads on its own: waiting never ends it.
     */
    private static void awaitEarlier(CompletableFuture<Void> earlier, Duration left) {
        long wait = Math.min(SINGLE_FLIGHT_WAIT.toNanos(), Math.max(0, left.toNanos()));
        try {
            earlier.get(wait, TimeUnit.NANOSECONDS);
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
        } catch (ExecutionException | TimeoutException notThere) {
            // It failed or is still reading: this request reads itself.
        }
    }

    /** A result as the attempt's ledger kept it ({@code chat_tool_calls.result}): exactly the envelope the model received. */
    static ChatToolResult kept(ObjectMapper mapper, ChatKeptToolResult kept) {
        JsonNode node = mapper.readTree(kept.result());
        return new ChatToolResult(node.path("schemaVersion").asString(), kept.toolCallId(), kept.capabilityId(),
                node.path("dataVersion").asString(null), mapper.convertValue(node.path("items"), ITEMS),
                mapper.convertValue(node.path("evidenceIds"), STRINGS),
                node.path("truncated").isBoolean()
                        ? node.path("truncated").asBoolean() || node.path("withheld").path("items").asInt(0) > 0 : null,
                node.path("nextAllowed").isBoolean() ? node.path("nextAllowed").asBoolean() : null, null,
                node.has("paths") ? mapper.convertValue(node.path("paths"), PATHS) : List.of(),
                node.has("webResults") ? mapper.convertValue(node.path("webResults"), WEB) : List.of(), null);
    }

    private static McpSchema.CallToolResult refused(String code) {
        Map<String, Object> error = new LinkedHashMap<>();
        error.put("error", code);
        return McpSchema.CallToolResult.builder().structuredContent(error).addTextContent("{\"error\":\"" + code + "\"}")
                .isError(true).build();
    }
}
