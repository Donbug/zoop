package com.zoop.chat.orchestrator;

import com.zoop.chat.dto.ChatChoice;
import com.zoop.chat.executor.ChatRun;
import com.zoop.chat.executor.ChatRunControl;
import com.zoop.chat.orchestrator.ChatPlan.Mode;
import com.zoop.chat.orchestrator.ChatPlan.Planned;
import com.zoop.chat.tool.ChatBriefingRound;
import com.zoop.chat.tool.ChatCapability;
import com.zoop.chat.tool.ChatToolItem;
import com.zoop.chat.tool.ChatToolRequest;
import com.zoop.chat.tool.ChatToolResult;
import com.zoop.chat.tool.ChatToolRunner;
import java.time.Instant;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

/**
 * Runs a confirmed plan's stages in order and evaluates each dependent requirement's checkpoint before its stage (design
 * summary 5.2). Requirements of one stage run together; the same read (capability, targets and evidence scope) asked by two
 * requirements is made once. Targets go out in batches of five; {@code graph.path.read} reads from its first target, so each
 * of its calls carries that target and at most four of the others. A ZOOP document capability reads its fixed documents
 * instead of the requirement's targets.
 *
 * <ul>
 * <li>A call that timed out or found its data unavailable leaves the requirements it served unanswered
 * ({@code tool_unavailable}), and the requirements that depend on them too; the others go on ({@code faulted} keeps the
 * first such call, so the engine can still fail the job when nothing is answered). An adapter fault is a bug, not a
 * passing fault: it ends retrieval at once, with no checkpoint evaluated and no later stage run.</li>
 * <li>Checkpoint over the companies the source found: more than the condition allows (or more than a stage can fan out to)
 * stops with a clarification built from what was actually found; fewer makes the dependent requirement
 * {@code precondition_unmet}; none at all, when the source was not cut by a limit, lets the source answer that nothing was
 * found; none from a cut source is not "none" and the source becomes {@code results_truncated}.</li>
 * <li>Q07 on companies the question names: those that are not the member's are not read. None of them being the member's
 * makes the requirement {@code not_in_member_scope}; only some being theirs is noted beside the answer ({@code outside}).
 * A company named as a reference point is read with the member's companies, first, and noted when it is not one of them.</li>
 * </ul>
 */
final class ChatRetrieval {
    /** A requirement whose own read, or the read it depends on, timed out or found its data unavailable. */
    static final String TOOL_UNAVAILABLE = "tool_unavailable";

    /**
     * What retrieval produced: results per requirement, the limitations it decided, or a stop or failed call. {@code cut}
     * holds the requirements that read on only part of the member's companies (Q07: more than a stage fans out to).
     * {@code outside} holds the Q07 requirements that name a company that is not the member's, by how it was named.
     * {@code faulted} is the first call that left a requirement {@link #TOOL_UNAVAILABLE}, null when none did.
     */
    record Outcome(Map<String, List<ChatToolResult>> results, Map<String, String> limitations, Set<String> noneFound,
            ChatPlan.Stop stop, ChatToolResult failed, Set<String> cut, Map<String, Outside> outside,
            ChatToolResult faulted) {
        Outcome(Map<String, List<ChatToolResult>> results, Map<String, String> limitations, Set<String> noneFound,
                ChatPlan.Stop stop, ChatToolResult failed) {
            this(results, limitations, noneFound, stop, failed, Set.of(), Map.of(), null);
        }
    }

    /**
     * How a Q07 requirement named a company that is not the member's: as what it asks about ({@code NAMED}, not read), or as
     * the point the member's companies are related to ({@code ANCHOR}, read all the same).
     */
    enum Outside { NAMED, ANCHOR }

    private final ChatToolRunner runner;

    ChatRetrieval(ChatToolRunner runner) {
        this.runner = runner;
    }

    Outcome run(ChatRun run, ChatRunControl control, ChatPlan.Run plan) {
        Map<String, List<ChatToolResult>> results = new LinkedHashMap<>();
        Map<String, String> limitations = new LinkedHashMap<>();
        Set<String> noneFound = new LinkedHashSet<>();
        Set<String> cut = new LinkedHashSet<>();
        Map<String, Outside> outside = new LinkedHashMap<>();
        Map<String, Planned> byId = new HashMap<>();
        plan.requirements().forEach(p -> byId.put(p.id(), p));
        ChatToolResult faulted = null;
        for (int stage = 1; stage <= plan.stages(); stage++) {
            List<ChatToolRequest> calls = new ArrayList<>();
            Map<String, Integer> callIndex = new HashMap<>();
            Map<String, List<Integer>> owned = new LinkedHashMap<>();
            for (Planned p : plan.requirements()) {
                if (p.stage() != stage || p.mode() != Mode.TOOLS || limitations.containsKey(p.id())) continue;
                List<String> targets = p.targets();
                if (p.dependsOn() != null) {
                    var source = p.dependsOn().requirementId();
                    if (limitations.containsKey(source)) {
                        // What it depends on could not be read: the same fault, not a condition the source failed.
                        limitations.put(p.id(), TOOL_UNAVAILABLE.equals(limitations.get(source)) ? TOOL_UNAVAILABLE
                                : "precondition_unmet");
                        continue;
                    }
                    Found found = found(results.getOrDefault(source, List.of()));
                    List<String> anchors = p.targets().stream().filter(ChatPlanner::companyId).toList();
                    if (p.onScope()) {
                        // The scope source reads the companies the question names, or the member's companies.
                        Planned scope = byId.get(source);
                        List<String> named = scope.targetSource() == ChatPlan.TargetSource.QUESTION ? scope.targets()
                                : List.of();
                        List<String> asked = named.isEmpty() ? anchors : named;
                        if (!found.truncated() && !found.companies().isEmpty()
                                && !found.companies().keySet().containsAll(asked)) {
                            outside.put(p.id(), named.isEmpty() ? Outside.ANCHOR : Outside.NAMED);
                        }
                        // None of the companies it is about is the member's: nothing of theirs to read.
                        if (!named.isEmpty() && found.companies().isEmpty()) {
                            limitations.put(p.id(), "not_in_member_scope");
                            continue;
                        }
                        // The member's own companies: having none is the answer, and reading only some of them is noted.
                        if (found.companies().isEmpty() && !found.truncated()) {
                            noneFound.add(p.id());
                            continue;
                        }
                        if (found.truncated()) cut.add(p.id());
                    }
                    var decision = checkpoint(p.dependsOn(), found.companies().size());
                    if (decision == Checkpoint.EXCESS) {
                        return new Outcome(results, limitations, noneFound,
                                ChatPlanner.clarify(run, "checkpoint_excess", choices(found, p.dependsOn())), null);
                    }
                    if (found.companies().isEmpty()) {
                        if (found.truncated()) limitations.put(source, "results_truncated");
                        else noneFound.add(source);
                    }
                    if (decision == Checkpoint.UNDER) {
                        limitations.put(p.id(), "precondition_unmet");
                        continue;
                    }
                    if (p.onScope()) {
                        // A reference point first (a path reads from its first target), then the member's companies, then
                        // a named issue.
                        Set<String> read = new LinkedHashSet<>(anchors);
                        read.addAll(found.companies().keySet());
                        read.addAll(p.targets());
                        targets = List.copyOf(read);
                    } else {
                        targets = List.copyOf(found.companies().keySet());
                    }
                }
                for (ChatCapability capability : p.capabilities()) {
                    // The member's narrowed evidence selection bounds the reads of the requirement's own targets, never
                    // the fixed ZOOP documents, which it is not about.
                    boolean fixed = !capability.documents().isEmpty();
                    var read = fixed ? capability.documents()
                            : capability == ChatCapability.BRIEFING_READ ? briefingTargets(run, p, targets)
                            : capability == ChatCapability.SELECTION_RULE_READ ? selectionTargets(run, p, targets) : targets;
                    List<String> scope = fixed ? null : p.evidenceScope();
                    Instant since = capability == ChatCapability.GRAPH_VERSION_DIFF ? since(run, p).orElse(null) : null;
                    for (List<String> chunk : batches(capability, read)) {
                        String key = capability.id() + "\u0000" + String.join("\u0000", chunk) + "\u0001"
                                + (scope == null ? "*" : String.join("\u0000", scope)) + "\u0001" + since;
                        Integer index = callIndex.get(key);
                        if (index == null) {
                            index = calls.size();
                            callIndex.put(key, index);
                            calls.add(new ChatToolRequest(capability.id(), chunk, ChatToolRequest.MAX_LIMIT, scope, since));
                        }
                        owned.computeIfAbsent(p.id(), k -> new ArrayList<>()).add(index);
                    }
                }
            }
            if (calls.isEmpty()) continue;
            List<ChatToolResult> stageResults = runner.runStage(run, control, 1, calls);
            for (ChatToolResult result : stageResults) {
                if (!result.succeeded() && !passing(result)) return new Outcome(results, limitations, noneFound, null, result);
            }
            for (var entry : owned.entrySet()) {
                List<ChatToolResult> mine = entry.getValue().stream().map(stageResults::get).toList();
                Optional<ChatToolResult> fault = mine.stream().filter(r -> !r.succeeded()).findFirst();
                if (fault.isEmpty()) {
                    results.put(entry.getKey(), mine);
                    continue;
                }
                // Part of a requirement's reads is not its answer: the whole requirement is left unanswered.
                limitations.put(entry.getKey(), TOOL_UNAVAILABLE);
                if (faulted == null) faulted = fault.get();
            }
        }
        for (Planned p : plan.requirements()) {
            // An independent lookup that found nothing and was not cut may say so.
            if (p.mode() == Mode.TOOLS && !limitations.containsKey(p.id()) && results.containsKey(p.id())
                    && results.get(p.id()).stream().allMatch(r -> r.items().isEmpty() && !r.truncated())) {
                noneFound.add(p.id());
            }
        }
        return new Outcome(results, limitations, noneFound, null, null, cut, outside, faulted);
    }

    /** A timeout or unavailable data: a fault of the moment that leaves its requirement unanswered, not a bug. */
    private static boolean passing(ChatToolResult failed) {
        return ChatToolRunner.TIMEOUT.equals(failed.error()) || ChatToolRunner.UNAVAILABLE.equals(failed.error());
    }

    /**
     * The period a comparison compares with: the one the requirement's own words write ({@link ChatPeriods}), else the one
     * the member selected with the question, else the one the last answers used; empty for "the previous public graph".
     */
    static Optional<ChatPeriods.Period> period(ChatRun run, Planned p) {
        var written = ChatPeriods.parse(p.label(), run.askedAt());
        if (written.isPresent() || run.period() == null) return written;
        var selected = run.period();
        return Optional.of(new ChatPeriods.Period(LocalDate.parse(selected.start()), LocalDate.parse(selected.end()), null));
    }

    /**
     * A briefing read's targets: the round the requirement's words name ({@link ChatBriefingRound#ref}, from its own day or
     * edition, else the latest), then the companies it names, to keep only their issues.
     */
    static List<String> briefingTargets(ChatRun run, Planned p, List<String> targets) {
        LocalDate today = LocalDate.ofInstant(run.askedAt(), ChatPeriods.KST);
        var day = ChatPeriods.parse(p.label(), run.askedAt()).filter(d -> d.start().equals(d.end())).map(d -> d.start());
        List<String> read = new ArrayList<>();
        read.add(ChatBriefingRound.ref(p.label(), day.orElse(null), today));
        targets.stream().filter(t -> ChatPlanner.companyId(t) && !ChatBriefingRound.isRef(t))
                .limit(ChatToolRequest.MAX_TARGETS - 1).forEach(read::add);
        return List.copyOf(read);
    }

    /**
     * A selection read's targets: the round the requirement's words name, as for a briefing read, then the issues it
     * names (a selection is about issues, never companies).
     */
    static List<String> selectionTargets(ChatRun run, Planned p, List<String> targets) {
        List<String> read = new ArrayList<>();
        read.add(briefingTargets(run, p, List.of()).getFirst());
        targets.stream().filter(t -> !ChatBriefingRound.isRef(t) && !ChatPlanner.companyId(t))
                .limit(ChatToolRequest.MAX_TARGETS - 1).forEach(read::add);
        return List.copyOf(read);
    }

    private static Optional<Instant> since(ChatRun run, Planned p) {
        return period(run, p).map(ChatPeriods.Period::startInstant);
    }

    /** The target lists of one capability's calls; {@link ChatPlanner#chunks} counts them. */
    static List<List<String>> batches(ChatCapability capability, List<String> targets) {
        List<List<String>> batches = new ArrayList<>();
        if (capability == ChatCapability.GRAPH_PATH_READ && targets.size() > 1) {
            String first = targets.getFirst();
            int per = ChatToolRequest.MAX_TARGETS - 1;
            for (int from = 1; from < targets.size(); from += per) {
                List<String> batch = new ArrayList<>();
                batch.add(first);
                batch.addAll(targets.subList(from, Math.min(targets.size(), from + per)));
                batches.add(List.copyOf(batch));
            }
            return batches;
        }
        for (int from = 0; from < targets.size(); from += ChatToolRequest.MAX_TARGETS) {
            batches.add(targets.subList(from, Math.min(targets.size(), from + ChatToolRequest.MAX_TARGETS)));
        }
        return batches;
    }

    enum Checkpoint { MET, UNDER, EXCESS }

    static Checkpoint checkpoint(ChatRouteDecision.Dependency condition, int count) {
        int n = condition.count();
        return switch (condition.cardinality()) {
            case "exactly" -> count > n ? Checkpoint.EXCESS : count < n ? Checkpoint.UNDER : Checkpoint.MET;
            case "atMost" -> count > n ? Checkpoint.EXCESS : count == 0 ? Checkpoint.UNDER : Checkpoint.MET;
            default -> count > ChatToolRequest.MAX_TARGETS ? Checkpoint.EXCESS
                    : count < n ? Checkpoint.UNDER : Checkpoint.MET;
        };
    }

    /** The companies a source found (company items and the companies of other items), with display labels. */
    record Found(Map<String, String> companies, boolean truncated) { }

    static Found found(List<ChatToolResult> results) {
        Map<String, String> companies = new LinkedHashMap<>();
        boolean truncated = false;
        for (ChatToolResult result : results) {
            truncated |= Boolean.TRUE.equals(result.truncated());
            for (ChatToolItem item : result.items()) {
                if ("company".equals(item.kind())) companies.put(item.id(), item.label());
                for (String id : item.companyIds()) companies.putIfAbsent(id, id);
            }
        }
        return new Found(companies, truncated);
    }

    /**
     * The combinations of exactly {@code n} found companies, when there are at most six; otherwise none (free input). Ids are
     * opaque to the client; the label is what the next run reads back.
     */
    static List<ChatChoice> choices(Found found, ChatRouteDecision.Dependency condition) {
        List<String> ids = List.copyOf(found.companies().keySet());
        int n = "exactly".equals(condition.cardinality()) ? condition.count() : 0;
        if (n == 0 || binomial(ids.size(), n) > ChatPlanner.MAX_CHOICES) return List.of();
        List<ChatChoice> choices = new ArrayList<>();
        combine(ids, n, 0, new ArrayList<>(), pick -> choices.add(new ChatChoice("pick-" + (choices.size() + 1),
                String.join(" · ", pick.stream().map(found.companies()::get).toList()), "scope")));
        return choices;
    }

    private static long binomial(int size, int n) {
        long value = 1;
        for (int i = 0; i < n; i++) value = value * (size - i) / (i + 1);
        return value;
    }

    private static void combine(List<String> ids, int n, int from, List<String> pick,
            java.util.function.Consumer<List<String>> out) {
        if (pick.size() == n) {
            out.accept(List.copyOf(pick));
            return;
        }
        for (int i = from; i < ids.size(); i++) {
            pick.add(ids.get(i));
            combine(ids, n, i + 1, pick, out);
            pick.removeLast();
        }
    }
}
