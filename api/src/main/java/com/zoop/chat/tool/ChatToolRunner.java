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
 * <li>At most four calls of a stage run at once. A call has 3 seconds and the stage 10 seconds, never past the run's
 * deadline; a call that runs out ends {@code failed}/{@link #TIMEOUT} and its read is interrupted. A call that could not
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
    static final Duration RECORD_GRACE = Duration.ofSeconds(2);
    static final int MAX_CONCURRENT = 4;
    /** Reads of all runs that may be unfinished at once: four workers' worth of stages. */
    static final int MAX_IN_FLIGHT = 16;
    private static final Logger log = LoggerFactory.getLogger(ChatToolRunner.class);

    private final ChatToolRegistry registry;
    private final Duration stageLimit;
    private final Duration callLimit;
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
        this(registry, STAGE_LIMIT, CALL_LIMIT, RECORD_GRACE, MAX_IN_FLIGHT);
    }

    ChatToolRunner(ChatToolRegistry registry, Duration stageLimit, Duration callLimit, Duration recordGrace,
            int maxInFlight) {
        this.registry = registry;
        this.stageLimit = stageLimit;
        this.callLimit = callLimit;
        this.recordGrace = recordGrace;
        this.inFlight = new Semaphore(maxInFlight);
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
            if (!slot(inFlight, stageEnd - System.nanoTime())) {
                slots.release();
                break;
            }
            String id = ids.get(i);
            ChatToolRequest call = calls.get(i);
            ChatTool tool = bindings.get(i).tool();
            try {
                control.toolCallStarted(id);
            } catch (ChatRunSuperseded lost) {
                slots.release();
                inFlight.release();
                superseded.set(true);
                break;
            }
            long budget = Math.min(callLimit.toNanos(), stageEnd - System.nanoTime());
            if (budget <= 0) {
                // Its start was recorded too late: it runs out without being made.
                slots.release();
                inFlight.release();
                started.add(CompletableFuture.supplyAsync(
                        () -> finish(control, id, call, null, new TimeoutException(), superseded), records));
                continue;
            }
            // The task always runs (never cancelled before it starts), so its slots are always given back; a timeout
            // interrupts the thread reading instead.
            CompletableFuture<ChatToolOutput> read = new CompletableFuture<>();
            AtomicReference<Thread> reader = new AtomicReference<>();
            pool.execute(() -> {
                reader.set(Thread.currentThread());
                try {
                    if (!read.isDone()) read.complete(tool.read(scope, call));
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
            started.add(read.handleAsync((output, error) -> finish(control, id, call, output, error, superseded),
                    records));
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
        if (call.evidenceScope() != null && !call.evidenceScope().containsAll(output.evidenceIds())) {
            return "evidence outside the requested scope";
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
