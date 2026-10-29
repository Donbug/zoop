package com.zoop.chat.tool;

import com.zoop.chat.executor.ChatRun;
import com.zoop.chat.executor.ChatRunControl;
import com.zoop.chat.executor.ChatRunSuperseded;
import com.zoop.chat.executor.ChatToolCallRefused;
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
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Semaphore;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;
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
 * <li>At most four calls of a stage run at once. A call has 3 seconds, a graph computation ({@code zoop-graph-read}:
 * paths, version comparison) 5 seconds, a web search 7 seconds, and the stage 10 seconds, never past the run's deadline; a call that runs out ends {@code failed}/{@link #TIMEOUT} and its read is interrupted. A call that could not
 * start within the stage stays reserved and is closed as {@code cancelled} with the job, and a call whose start was
 * recorded only after the stage ran out is not run at all.</li>
 * <li>Reads that have not ended, timed-out ones included, hold a runner-wide slot ({@link #MAX_IN_FLIGHT}) until their
 * thread really returns, so reads stuck in one job reduce what the next ones may start instead of piling up.</li>
 * <li>The stage waits for its records at most {@link #RECORD_GRACE} past its end. A call whose record could not be made in
 * time, or failed, is never reported as a result: the stage throws {@link ChatRunSuperseded}, the run stores nothing, and
 * the job ends through lease recovery.</li>
 * <li>The graph version and asOf come from the run's frozen context, never from the plan. Output evidence outside a call's
 * {@code evidenceScope} is an adapter fault.</li>
 * <li>A failed call is never an empty result. Whether a stage may continue is the orchestrator's decision (a tool failure
 * ends the job as a failure before any count is evaluated).</li>
 * </ul>
 */
@Component
public class ChatToolRunner implements AutoCloseable {
    public static final String TIMEOUT = "tool_timeout";
    public static final String UNAVAILABLE = "tool_unavailable";
    public static final String FAILED = "tool_failed";
    static final Duration STAGE_LIMIT = Duration.ofSeconds(10);
    static final Duration CALL_LIMIT = Duration.ofSeconds(3);
    static final Duration GRAPH_CALL_LIMIT = Duration.ofSeconds(5);
    static final Duration WEB_CALL_LIMIT = Duration.ofSeconds(7);
    static final Duration RECORD_GRACE = Duration.ofSeconds(2);
    static final int MAX_CONCURRENT = 4;
    /** Reads of all runs that may be unfinished at once: four workers' worth of stages. */
    static final int MAX_IN_FLIGHT = 16;
    private static final Logger log = LoggerFactory.getLogger(ChatToolRunner.class);

    private final ChatToolRegistry registry;
    private final Duration stageLimit;
    private final Duration callLimit;
    private final Duration graphCallLimit;
    private final Duration recordGrace;
    private final Semaphore inFlight;
    private final ExecutorService pool = Executors.newVirtualThreadPerTaskExecutor();
    /**
     * Records run on their own platform threads: a read that keeps a CPU busy (and so its virtual-thread carrier) can never
     * hold back the record that ends a call.
     */
    private final ExecutorService records = Executors.newFixedThreadPool(MAX_CONCURRENT, Thread.ofPlatform().daemon()
            .name("chat-tool-record-", 0).factory());

    @Autowired
    public ChatToolRunner(ChatToolRegistry registry) {
        this(registry, STAGE_LIMIT, CALL_LIMIT, GRAPH_CALL_LIMIT, RECORD_GRACE, MAX_IN_FLIGHT);
    }

    ChatToolRunner(ChatToolRegistry registry, Duration stageLimit, Duration callLimit, Duration graphCallLimit,
            Duration recordGrace, int maxInFlight) {
        this.registry = registry;
        this.stageLimit = stageLimit;
        this.callLimit = callLimit;
        this.graphCallLimit = graphCallLimit;
        this.recordGrace = recordGrace;
        this.inFlight = new Semaphore(maxInFlight);
    }

    /** Runs the stage's calls and returns one result per call, in plan order. */
    public List<ChatToolResult> runStage(ChatRun run, ChatRunControl control, int planRevision,
            List<ChatToolRequest> calls) {
        return runStage(run, control, planRevision, calls, null);
    }

    /**
     * Runs the stage's calls like {@link #runStage(ChatRun, ChatRunControl, int, List)}; {@code via}, when not null, names
     * the transport the calls came through (the chat MCP endpoint: {@code mcp}) and is kept in each call's request record.
     */
    public List<ChatToolResult> runStage(ChatRun run, ChatRunControl control, int planRevision,
            List<ChatToolRequest> calls, String via) {
        // Every reservation is built (every capability bound) before anything is reserved.
        List<ChatToolCallReservation> reservations = calls.stream().map(call -> reservation(run, call, via)).toList();
        List<String> ids = control.reserveToolCalls(planRevision, reservations);
        return runReserved(run, control, ids, calls, Delivery.NONE);
    }

    /**
     * What the caller of {@link #runReserved} does with a usable read before it is recorded: narrow it to what may be passed
     * on (the result and the ledger then show only that), refuse it with a failure code (recorded {@code failed}, no result
     * reported), or keep its result envelope (JSON) on the ledger with the success.
     *
     * <p>{@link #pass} may read (grants, sources): it runs on the read's own thread inside the call's time limit and
     * runner-wide slot, so a slow check times the call out like a slow read and never holds the threads that record calls.
     * {@link #refuse} and {@link #keep} run while the call is recorded and must not block.
     */
    public interface Delivery {
        Delivery NONE = new Delivery() { };

        default ChatToolOutput pass(ChatToolOutput output) {
            return output;
        }

        default String refuse(ChatToolOutput output) {
            return null;
        }

        default String keep(ChatToolResult result) {
            return null;
        }
    }

    /**
     * The {@code chat_tool_calls} reservation of one call of {@code run}: its kept request structure and the digest of
     * capability and request, which identifies the exact call. {@code via} as in
     * {@link #runStage(ChatRun, ChatRunControl, int, List, String)}. Throws {@link IllegalArgumentException} for an unbound
     * capability.
     */
    public ChatToolCallReservation reservation(ChatRun run, ChatToolRequest call, String via) {
        return reservation(binding(call), scope(run), call, via);
    }

    /**
     * Runs calls that are already reserved ({@code ids}, in the same order as {@code calls}) under the same limits and
     * records as {@link #runStage}, with {@code delivery} deciding on each usable read before it is recorded.
     */
    public List<ChatToolResult> runReserved(ChatRun run, ChatRunControl control, List<String> ids,
            List<ChatToolRequest> calls, Delivery delivery) {
        if (ids.size() != calls.size()) throw new IllegalArgumentException("one reserved id per call");
        return run(run, control, ids, calls, calls.stream().map(call -> binding(call).tool()).toList(), delivery, false);
    }

    /**
     * Runs one call its caller already started ({@link ChatRunControl#claimToolCall}: reserved → running in the same step
     * that picked it) under the same limits and records as {@link #runReserved}.
     */
    public ChatToolResult runClaimed(ChatRun run, ChatRunControl control, String id, ChatToolRequest call,
            Delivery delivery) {
        return run(run, control, List.of(id), List.of(call), List.of(binding(call).tool()), delivery, true).getFirst();
    }

    /**
     * Ends a call its caller already started ({@link ChatRunControl#claimToolCall}) with {@code earlier}, the output an
     * identical earlier call of the run returned, instead of reading again (MCP actions contract 3.3): it is passed through
     * {@code delivery} (whose checks run again now, so a grant withdrawn since is applied) and recorded exactly like a read,
     * under the same limits.
     */
    public ChatToolResult runCached(ChatRun run, ChatRunControl control, String id, ChatToolRequest call,
            ChatToolOutput earlier, Delivery delivery) {
        ChatCapability capability = binding(call).tool().capability();
        ChatTool reuse = new ChatTool() {
            @Override
            public ChatCapability capability() {
                return capability;
            }

            @Override
            public ChatToolOutput read(ChatToolScope scope, ChatToolRequest request) {
                return earlier;
            }
        };
        return run(run, control, List.of(id), List.of(call), List.of(reuse), delivery, true).getFirst();
    }

    /** Runs {@code calls} with {@code tools}; {@code alreadyStarted} when the caller already recorded their start. */
    private List<ChatToolResult> run(ChatRun run, ChatRunControl control, List<String> ids, List<ChatToolRequest> calls,
            List<ChatTool> tools, Delivery delivery, boolean alreadyStarted) {
        ChatToolScope scope = scope(run);

        long stageEnd = System.nanoTime() + Math.min(stageLimit.toNanos(), Math.max(0, control.remaining().toNanos()));
        Semaphore slots = new Semaphore(MAX_CONCURRENT);
        AtomicBoolean superseded = new AtomicBoolean();
        List<CompletableFuture<ChatToolResult>> started = new ArrayList<>();
        for (int i = 0; i < calls.size() && !superseded.get(); i++) {
            if (!slot(slots, stageEnd - System.nanoTime())) break;
            if (!slot(inFlight, stageEnd - System.nanoTime())) {
                slots.release();
                break;
            }
            String id = ids.get(i);
            ChatToolRequest call = calls.get(i);
            ChatTool tool = tools.get(i);
            try {
                if (!alreadyStarted) control.toolCallStarted(id);
            } catch (ChatRunSuperseded lost) {
                slots.release();
                inFlight.release();
                superseded.set(true);
                break;
            }
            long budget = Math.min(limit(tool.capability()).toNanos(), stageEnd - System.nanoTime());
            if (budget <= 0) {
                // Its start was recorded too late: it runs out without being made.
                slots.release();
                inFlight.release();
                started.add(CompletableFuture.supplyAsync(
                        () -> finish(control, id, call, null, new TimeoutException(), superseded, delivery), records));
                continue;
            }
            // The task always runs (never cancelled before it starts), so its slots are always given back; a timeout
            // interrupts the thread reading instead.
            CompletableFuture<ChatToolOutput> read = new CompletableFuture<>();
            AtomicReference<Thread> reader = new AtomicReference<>();
            pool.execute(() -> {
                reader.set(Thread.currentThread());
                try {
                    if (!read.isDone()) read.complete(passed(call, tool.read(scope, call), delivery));
                } catch (Throwable error) {
                    read.completeExceptionally(error);
                } finally {
                    reader.set(null);
                    Thread.interrupted();
                    slots.release();
                    inFlight.release();
                }
            });
            read.orTimeout(budget, TimeUnit.NANOSECONDS).whenComplete((output, error) -> {
                Thread thread = reader.get();
                if (error instanceof TimeoutException && thread != null) thread.interrupt();
            });
            started.add(read.handleAsync((output, error) -> finish(control, id, call, output, error, superseded,
                    delivery), records));
        }
        awaitRecords(started, stageEnd, superseded);
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
        records.shutdownNow();
    }

    /** The time one call of {@code capability} has, before the stage and the run's deadline shorten it. */
    private Duration limit(ChatCapability capability) {
        if (capability.web()) return WEB_CALL_LIMIT;
        return "zoop-graph-read".equals(capability.group()) ? graphCallLimit : callLimit;
    }

    private ChatToolRegistry.Binding binding(ChatToolRequest call) {
        return registry.bind(call.capabilityId())
                .orElseThrow(() -> new IllegalArgumentException("unbound chat capability: " + call.capabilityId()));
    }

    private static ChatToolScope scope(ChatRun run) {
        return new ChatToolScope(run.jobId(), run.graphVersionId(), run.context().asOf(), run.memberId());
    }

    /** Waits for every started call to be recorded, at most {@code recordGrace} past the stage end. */
    private void awaitRecords(List<CompletableFuture<ChatToolResult>> started, long stageEnd, AtomicBoolean superseded) {
        long wait = Math.max(0, stageEnd - System.nanoTime()) + recordGrace.toNanos();
        try {
            CompletableFuture.allOf(started.toArray(CompletableFuture[]::new)).get(wait, TimeUnit.NANOSECONDS);
        } catch (TimeoutException late) {
            log.warn("chat tool calls were not recorded in time; the run stops");
            superseded.set(true);
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            superseded.set(true);
        } catch (ExecutionException unexpected) {
            // finish() never throws; a failure here is a bug and the run must not go on with unknown records.
            log.warn("chat tool stage failed unexpectedly", unexpected);
            superseded.set(true);
        }
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

    /** A usable output as {@code delivery} passes it on, on the read's thread; an unusable one is left for the record. */
    private static ChatToolOutput passed(ChatToolRequest call, ChatToolOutput output, Delivery delivery) {
        return invalid(call, output) == null ? delivery.pass(output) : output;
    }

    /**
     * Records the end of one call. {@code output} is already what {@link Delivery#pass} let through (a subset of a usable
     * read is still usable); nothing here reads or waits beyond the record itself.
     */
    private ChatToolResult finish(ChatRunControl control, String id, ChatToolRequest call, ChatToolOutput output,
            Throwable error, AtomicBoolean superseded, Delivery delivery) {
        ChatToolResult result;
        ChatToolCallEnd end;
        String problem = error == null ? invalid(call, output) : null;
        String refused = error == null && problem == null ? delivery.refuse(output) : null;
        if (refused != null) {
            // A usable read the caller cannot pass on (an MCP result over its size limit, or one its send grants cannot be
            // checked for): recorded as that failure, so the ledger never shows evidence as delivered that was not.
            result = ChatToolResult.failed(id, call.capabilityId(), refused);
            end = ChatToolCallEnd.failed(refused);
        } else if (error == null && problem == null) {
            result = ChatToolResult.succeeded(id, call.capabilityId(), output);
            end = new ChatToolCallEnd("succeeded", null, output.dataVersion(), output.evidenceIds(), output.truncated(),
                    output.nextAllowed(), delivery.keep(result));
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
        } catch (ChatToolCallRefused overLimit) {
            // Recorded as that failure (a job limit only the record can check): the result is not delivered.
            result = ChatToolResult.failed(id, call.capabilityId(), overLimit.code());
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
        if (call.evidenceScope() != null && !call.evidenceScope().containsAll(output.evidenceIds())) {
            return "evidence outside the requested scope";
        }
        return null;
    }

    /** The allowed request structure {@code chat_tool_calls} keeps, and its digest. */
    private static ChatToolCallReservation reservation(ChatToolRegistry.Binding binding, ChatToolScope scope,
            ChatToolRequest call, String via) {
        ObjectNode meta = StrictJson.newObject();
        if (via != null) meta.put("via", via);
        var targets = meta.putArray("targets");
        call.targets().forEach(targets::add);
        meta.put("limit", call.limit());
        meta.put("graphVersion", scope.graphVersionId());
        meta.put("asOf", scope.asOf() == null ? null : scope.asOf().toString());
        if (call.evidenceScope() != null) {
            var evidence = meta.putArray("evidenceScope");
            call.evidenceScope().forEach(evidence::add);
        }
        if (call.since() != null) meta.put("since", call.since().toString());
        ObjectNode input = StrictJson.newObject();
        input.put("capabilityId", binding.capability().id());
        input.set("request", meta);
        return new ChatToolCallReservation(ChatToolRegistry.VERSION, binding.capability().group(),
                binding.capability().id(), binding.toolId(), ChatToolRegistry.SCHEMA_VERSION, Canonical.digest(input),
                Canonical.write(meta));
    }
}
