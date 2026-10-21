package com.zoop.chat.tool;

import com.zoop.chat.executor.ChatRun;
import com.zoop.chat.executor.ChatRunControl;
import com.zoop.chat.executor.ChatRunSuperseded;
import com.zoop.chat.executor.ChatToolCallReservation;
import com.zoop.chat.repository.ChatToolCallEnd;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import java.time.Duration;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Semaphore;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicBoolean;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;
import tools.jackson.databind.node.ObjectNode;

/**
 * Runs one stage of a confirmed tool plan (AI chatbot implementation plan, stages 2 and 4) and records every call in
 * {@code chat_tool_calls} through the run's fenced control.
 *
 * <ul>
 * <li>Every capability must be bound in {@link ChatToolRegistry} before anything is reserved; an unbound one refuses the
 * whole stage. The stage's calls are reserved first ({@code reserved}, at most 12 per attempt) and each is marked
 * {@code running} just before it starts.</li>
 * <li>At most four calls run at once. A call has 3 seconds and the stage 10 seconds, never past the run's deadline; a call
 * that runs out ends {@code failed}/{@link #TIMEOUT}, and a call that could not start within the stage stays reserved and is
 * closed as {@code cancelled} with the job. A timed-out read is abandoned, not interrupted: it is read-only.</li>
 * <li>The graph version and asOf come from the run's frozen context, never from the plan.</li>
 * <li>A failed call is never an empty result. Whether a stage may continue is the orchestrator's decision (a tool failure
 * ends the job as a failure before any count is evaluated).</li>
 * <li>Once the run no longer owns its job, nothing more starts and the stage throws {@link ChatRunSuperseded}.</li>
 * </ul>
 */
@Component
public class ChatToolRunner implements AutoCloseable {
    public static final String TIMEOUT = "tool_timeout";
    public static final String UNAVAILABLE = "tool_unavailable";
    public static final String FAILED = "tool_failed";
    static final Duration STAGE_LIMIT = Duration.ofSeconds(10);
    static final Duration CALL_LIMIT = Duration.ofSeconds(3);
    static final int MAX_CONCURRENT = 4;
    private static final Logger log = LoggerFactory.getLogger(ChatToolRunner.class);

    private final ChatToolRegistry registry;
    private final Duration stageLimit;
    private final Duration callLimit;
    private final ExecutorService pool = Executors.newVirtualThreadPerTaskExecutor();

    @Autowired
    public ChatToolRunner(ChatToolRegistry registry) {
        this(registry, STAGE_LIMIT, CALL_LIMIT);
    }

    ChatToolRunner(ChatToolRegistry registry, Duration stageLimit, Duration callLimit) {
        this.registry = registry;
        this.stageLimit = stageLimit;
        this.callLimit = callLimit;
    }

    /** Runs the stage's calls and returns one result per call, in plan order. */
    public List<ChatToolResult> runStage(ChatRun run, ChatRunControl control, int planRevision,
            List<ChatToolRequest> calls) {
        List<ChatToolRegistry.Binding> bindings = calls.stream().map(call -> registry.bind(call.capabilityId())
                .orElseThrow(() -> new IllegalArgumentException("unbound chat capability: " + call.capabilityId())))
                .toList();
        ChatToolScope scope = new ChatToolScope(run.jobId(), run.graphVersionId(), run.context().asOf());
        List<ChatToolCallReservation> reservations = new ArrayList<>();
        for (int i = 0; i < calls.size(); i++) reservations.add(reservation(bindings.get(i), scope, calls.get(i)));
        List<String> ids = control.reserveToolCalls(planRevision, reservations);

        long stageEnd = System.nanoTime() + Math.min(stageLimit.toNanos(), Math.max(0, control.remaining().toNanos()));
        Semaphore slots = new Semaphore(MAX_CONCURRENT);
        AtomicBoolean superseded = new AtomicBoolean();
        List<CompletableFuture<ChatToolResult>> started = new ArrayList<>();
        for (int i = 0; i < calls.size() && !superseded.get(); i++) {
            if (!slot(slots, stageEnd - System.nanoTime())) break;
            String id = ids.get(i);
            ChatToolRequest call = calls.get(i);
            ChatTool tool = bindings.get(i).tool();
            try {
                control.toolCallStarted(id);
            } catch (ChatRunSuperseded lost) {
                slots.release();
                superseded.set(true);
                break;
            }
            long budget = Math.min(callLimit.toNanos(), stageEnd - System.nanoTime());
            started.add(CompletableFuture.supplyAsync(() -> {
                try {
                    return tool.read(scope, call);
                } finally {
                    slots.release();
                }
            }, pool).orTimeout(Math.max(1, budget), TimeUnit.NANOSECONDS)
                    .handleAsync((output, error) -> finish(control, id, call, output, error, superseded), pool));
        }
        CompletableFuture.allOf(started.toArray(CompletableFuture[]::new)).join();
        if (superseded.get()) throw new ChatRunSuperseded();

        List<ChatToolResult> results = new ArrayList<>();
        for (int i = 0; i < calls.size(); i++) {
            results.add(i < started.size() ? started.get(i).join()
                    : ChatToolResult.failed(ids.get(i), calls.get(i).capabilityId(), TIMEOUT));
        }
        return List.copyOf(results);
    }

    @Override
    public void close() {
        pool.shutdownNow();
    }

    private static boolean slot(Semaphore slots, long nanos) {
        if (nanos <= 0) return false;
        try {
            return slots.tryAcquire(nanos, TimeUnit.NANOSECONDS);
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            return false;
        }
    }

    private ChatToolResult finish(ChatRunControl control, String id, ChatToolRequest call, ChatToolOutput output,
            Throwable error, AtomicBoolean superseded) {
        ChatToolResult result;
        ChatToolCallEnd end;
        String problem = error == null ? invalid(call, output) : null;
        if (error == null && problem == null) {
            result = ChatToolResult.succeeded(id, call.capabilityId(), output);
            end = new ChatToolCallEnd("succeeded", null, output.dataVersion(), output.evidenceIds(), output.truncated(),
                    output.nextAllowed());
        } else {
            Throwable cause = error instanceof CompletionException wrapped && wrapped.getCause() != null
                    ? wrapped.getCause() : error;
            String code = cause instanceof TimeoutException ? TIMEOUT
                    : cause instanceof ChatToolUnavailable ? UNAVAILABLE : FAILED;
            if (FAILED.equals(code)) {
                log.warn("chat tool {} failed: {}", call.capabilityId(), problem == null ? "exception" : problem, cause);
            }
            result = ChatToolResult.failed(id, call.capabilityId(), code);
            end = ChatToolCallEnd.failed(code);
        }
        try {
            control.toolCallFinished(id, end);
        } catch (ChatRunSuperseded lost) {
            superseded.set(true);
        } catch (RuntimeException unrecorded) {
            log.warn("chat tool call {} could not be recorded", id, unrecorded);
            superseded.set(true);
        }
        return result;
    }

    /** What makes an adapter's output unusable: a missing version, evidence over the limit or not passed on. */
    private static String invalid(ChatToolRequest call, ChatToolOutput output) {
        if (output == null || output.dataVersion() == null) return "no data version";
        if (output.evidenceIds().size() > call.limit() || new HashSet<>(output.evidenceIds()).size()
                != output.evidenceIds().size()) return "evidence over the limit or repeated";
        var passed = new HashSet<>(output.evidenceIds());
        if (output.items().stream().anyMatch(item -> !passed.containsAll(item.evidenceIds()))) {
            return "item evidence not passed on";
        }
        return null;
    }

    /** The allowed request structure {@code chat_tool_calls} keeps, and its digest. */
    private static ChatToolCallReservation reservation(ChatToolRegistry.Binding binding, ChatToolScope scope,
            ChatToolRequest call) {
        ObjectNode meta = StrictJson.newObject();
        var targets = meta.putArray("targets");
        call.targets().forEach(targets::add);
        meta.put("limit", call.limit());
        meta.put("graphVersion", scope.graphVersionId());
        meta.put("asOf", scope.asOf() == null ? null : scope.asOf().toString());
        ObjectNode input = StrictJson.newObject();
        input.put("capabilityId", binding.capability().id());
        input.set("request", meta);
        return new ChatToolCallReservation(ChatToolRegistry.VERSION, binding.capability().group(),
                binding.capability().id(), binding.toolId(), ChatToolRegistry.SCHEMA_VERSION, Canonical.digest(input),
                Canonical.write(meta));
    }
}
