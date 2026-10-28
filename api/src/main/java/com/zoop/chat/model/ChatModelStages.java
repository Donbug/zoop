package com.zoop.chat.model;

import java.util.ArrayList;
import java.util.EnumMap;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.regex.Pattern;

import com.zoop.ai.AiClientException;
import com.zoop.ai.AiServiceRejectionException;
import com.zoop.ai.chat.ChatStageCall;
import com.zoop.ai.chat.ChatStageClient;
import com.zoop.ai.chat.ChatStageReply;
import com.zoop.chat.dto.Citation;
import com.zoop.chat.executor.ChatRun;
import com.zoop.chat.orchestrator.ChatBranchContext;
import com.zoop.chat.orchestrator.ChatCitationSource;
import com.zoop.chat.orchestrator.ChatGeneratedAnswer;
import com.zoop.chat.orchestrator.ChatModels;
import com.zoop.chat.orchestrator.ChatModels.Failure.Fate;
import com.zoop.chat.orchestrator.ChatPlanner;
import com.zoop.chat.orchestrator.ChatQueryType;
import com.zoop.chat.orchestrator.ChatRouteDecision;
import com.zoop.chat.orchestrator.ChatSemanticVerdicts;
import com.zoop.chat.service.ChatCompanyProfiles;
import com.zoop.chat.service.ChatZoopDocs;
import com.zoop.chat.tool.ChatCapability;
import com.zoop.chat.tool.ChatToolItem;
import com.zoop.chat.tool.ChatToolPath;
import com.zoop.chat.tool.ChatToolResult;
import com.zoop.common.json.StrictJson;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

/**
 * The three orchestrator model ports over the AI service's chat stages ({@code zoop-ai-chat-1}). The server decides what is
 * sent: the router gets the question chain, the requirements split by {@link ChatRequirementSplitter} and the descriptions of
 * the bound capabilities; company and issue names are resolved here, never by the model. Company names
 * ({@link CompanyNameResolver}) are resolved before the router, so a name that fits several companies becomes a clarification
 * without any model call. Issue names ({@link IssueNameResolver}, over the run's pinned graph) are resolved after it and only
 * when a requirement may look something up, so a concept question never reads the graph; a shared issue name is then a
 * clarification after the router call. The generator and verifier get quotes built from the evidence records, each with the
 * {@code sourceId} the AI side's chat grant registry checks. No member id, account data or article text is sent.
 *
 * <p>Failures map to {@link ChatModels.Failure}: a stage whose request may have reached the provider is {@link Fate#UNKNOWN}
 * and never rerun; a policy or configuration refusal is {@link Fate#REFUSED}; anything else that sent nothing, or got a
 * definite provider failure or an answer of the wrong shape, is {@link Fate#NOT_SENT}. The invocation id is
 * {@code <jobId>.<attempt>.<stage>}, so a rerun of the job is a new invocation and a repeat of the same one is never sent
 * twice.
 */
public class ChatModelStages implements ChatModels.Router, ChatModels.Generator, ChatModels.Verifier {
    static final String ROUTER = "chat-router";
    static final String ANSWER = "chat-answer";
    static final String VERIFICATION = "chat-verification";
    static final int MAX_REQUIREMENTS = 6;
    static final int MAX_ITEMS = 50;
    static final int MAX_QUOTES = 20;
    static final int MAX_QUOTE = 2000;
    static final int MAX_LABEL = 300;
    static final int MAX_PATHS = 20;
    private static final Pattern EVIDENCE = Pattern.compile("ev-[0-9a-f]{64}");
    /**
     * Item kinds whose label is catalog or graph data (company names, issue titles, relation pairs) or a ZOOP document title,
     * not source text.
     */
    static final Set<String> SENT_ITEM_KINDS = Set.of("company", "issue", "edge", "zoop_doc");

    /** The S2-1 source id of an article: the {@code articles.provider} the chat grant registry is keyed by. */
    @FunctionalInterface
    public interface ArticleSources {
        Optional<String> sourceOf(String articleId);
    }

    private final ChatStageClient client;
    private final String mode;
    private final CompanyNameResolver names;
    private final IssueNameResolver issues;
    private final ChatCitationSource citations;
    private final ArticleSources sources;
    private final ChatModelRecorder recorder;

    public ChatModelStages(ChatStageClient client, String mode, CompanyNameResolver names, IssueNameResolver issues,
            ChatCitationSource citations, ArticleSources sources, ChatModelRecorder recorder) {
        this.client = client;
        this.mode = mode;
        this.names = names;
        this.issues = issues;
        this.citations = citations;
        this.sources = sources;
        this.recorder = recorder;
    }

    // ---------------------------------------------------------------- router

    /**
     * The question chain decides before any limit or ambiguity is judged (design summary: a reply reruns decomposition on the
     * root question and the answers in order). A free-text reply to a root that had more requirements than allowed replaces
     * them with its own; a company or issue the member named in a reply, or picked as a choice, resolves a shared name of the
     * root.
     */
    @Override
    public ChatRouteDecision route(ChatRun run, Set<String> boundCapabilities) {
        Set<String> picked = new HashSet<>();
        List<String> replies = new ArrayList<>();
        for (ChatRun.Turn turn : run.turns().subList(1, run.turns().size())) {
            if (turn.choiceId() != null) picked.add(turn.choiceId());
            else replies.add(turn.question());
        }
        List<ChatRequirementSplitter.Piece> pieces = effectiveRequirements(run.turns().getFirst().question(), replies);
        if (pieces.size() > MAX_REQUIREMENTS) {
            // More than the planner accepts: it asks the member to narrow the question; the router is not asked.
            return new ChatRouteDecision(pieces.stream().map(p -> requirement(p, Map.of(), Map.of(), List.of(), 0)).toList(), null);
        }
        // Companies are resolved before the router, so a shared company name asks without any model call.
        Resolved companies = resolve(pieces, replies, picked, IssueNameResolver.NONE);
        if (companies.ambiguity() != null) return new ChatRouteDecision(List.of(), companies.ambiguity());
        Map<String, List<String>> targets = companies.targets();

        ObjectNode input = StrictJson.newObject();
        input.set("turns", turns(run));
        ArrayNode requirements = input.putArray("requirements");
        for (var piece : pieces) {
            requirements.addObject().put("requirementId", piece.id()).put("text", piece.text()).put("explicit", true);
        }
        ArrayNode capabilities = input.putArray("capabilities");
        for (ChatCapability capability : ChatCapability.values()) {
            if (boundCapabilities.contains(capability.id())) {
                capabilities.addObject().put("capabilityId", capability.id()).put("description", capability.description());
            }
        }
        JsonNode answer = call(run, ROUTER, "router", input);
        ChatRouteDecision decision = decode(() -> {
            Map<String, JsonNode> routed = new HashMap<>();
            for (JsonNode r : array(answer, "requirements")) {
                if (routed.put(text(r, "requirementId"), r) != null) throw new IllegalArgumentException("duplicate");
            }
            if (!routed.keySet().equals(pieces.stream().map(ChatRequirementSplitter.Piece::id).collect(java.util.stream.Collectors.toSet()))) {
                throw new IllegalArgumentException("requirements differ");
            }
            List<ChatRouteDecision.Requirement> decided = new ArrayList<>();
            for (var piece : pieces) {
                JsonNode r = routed.get(piece.id());
                Map<ChatQueryType, Double> types = new EnumMap<>(ChatQueryType.class);
                probabilities(r, "types").forEach((k, v) -> types.put(ChatQueryType.valueOf(k), v));
                Map<String, Double> caps = new HashMap<>();
                probabilities(r, "capabilities").forEach((k, v) -> {
                    if (boundCapabilities.contains(k)) caps.put(k, v);
                });
                decided.add(requirement(piece, types, caps, targets.get(piece.id()), number(r.get("prohibitedAdvice"))));
            }
            return new ChatRouteDecision(decided, null);
        });

        // Issues are resolved only for a question that may read the pinned graph: a concept question or one that reads only
        // ZOOP's own documents (Q01) never does, so it is answered while the graph cannot be read. A graph that cannot be
        // read here is the reads' outage too, and ends the run as such, not as a model failure.
        if (decision.requirements().stream().noneMatch(r -> mayReadGraph(r, boundCapabilities))) return decision;
        Resolved named = resolve(pieces, replies, picked, issues.at(run.graphVersionId(), run.context().asOf()));
        if (named.ambiguity() != null) return new ChatRouteDecision(List.of(), named.ambiguity());
        return new ChatRouteDecision(decision.requirements().stream().map(r -> new ChatRouteDecision.Requirement(r.id(),
                r.label(), r.explicit(), r.types(), r.capabilities(), named.targets().get(r.id()), r.prohibitedAdvice(),
                r.dependsOn())).toList(), null);
    }

    /**
     * Whether the planner may give a requirement a read of the pinned graph: a type at its lowest band that allows a bound
     * capability reading the graph. It is the band at which a concept question naming a company or an issue also becomes a
     * question about it. Q02 allows no capability and Q01 only ZOOP document reads, which need no graph.
     */
    private static boolean mayReadGraph(ChatRouteDecision.Requirement requirement, Set<String> bound) {
        return requirement.types().entrySet().stream().filter(t -> t.getValue() >= ChatPlanner.REVIEW)
                .anyMatch(t -> t.getKey().capabilities().stream().anyMatch(c -> c.readsGraph() && bound.contains(c.id())));
    }

    /** Targets by requirement, or the shared name to ask about. */
    private record Resolved(Map<String, List<String>> targets, ChatRouteDecision.Ambiguity ambiguity) { }

    /**
     * The companies, and the issues {@code issueNames} knows, that each requirement names, in order; a requirement that names
     * none takes what the replies named. A name typed in a reply counts as a pick for a shared name of the question.
     */
    private Resolved resolve(List<ChatRequirementSplitter.Piece> pieces, List<String> replies, Set<String> chosen,
            IssueNameResolver.Names issueNames) {
        Set<String> picked = new HashSet<>(chosen);
        Map<String, List<String>> targets = new LinkedHashMap<>();
        List<String> fromReplies = new ArrayList<>();
        try {
            for (String reply : replies) {
                for (var mention : named(reply, issueNames)) {
                    resolved(mention, picked).ifPresent(id -> {
                        if (!fromReplies.contains(id)) fromReplies.add(id);
                    });
                }
            }
            picked.addAll(fromReplies);
            for (var piece : pieces) {
                List<String> ids = new ArrayList<>();
                for (var mention : named(piece.text(), issueNames)) {
                    Optional<String> id = resolved(mention, picked);
                    if (id.isEmpty()) {
                        return new Resolved(null, new ChatRouteDecision.Ambiguity(mention.kind(), mention.candidates()));
                    }
                    if (!ids.contains(id.get())) ids.add(id.get());
                }
                targets.put(piece.id(), ids.isEmpty() ? List.copyOf(fromReplies) : List.copyOf(ids));
            }
        } catch (RuntimeException unreadable) {
            throw new ChatModels.Failure(Fate.NOT_SENT, "company or issue names could not be resolved");
        }
        return new Resolved(targets, null);
    }

    /** The root's requirements, replaced in order by a free-text reply's own while they are more than the planner accepts. */
    static List<ChatRequirementSplitter.Piece> effectiveRequirements(String root, List<String> replies) {
        List<ChatRequirementSplitter.Piece> pieces = ChatRequirementSplitter.split(root);
        for (String reply : replies) {
            if (pieces.size() > MAX_REQUIREMENTS) pieces = ChatRequirementSplitter.split(reply);
        }
        return pieces;
    }

    private static ChatRouteDecision.Requirement requirement(ChatRequirementSplitter.Piece piece, Map<ChatQueryType, Double> types,
            Map<String, Double> capabilities, List<String> targets, double advice) {
        return new ChatRouteDecision.Requirement(piece.id(), piece.text(), true, types, capabilities, targets, advice, null);
    }

    /**
     * A name in the text and what it may mean, as a clarification would offer it: companies (choice kind {@code company})
     * first, then issues (kind {@code other}; the public choice kinds have none for issues).
     */
    private record Named(String kind, List<ChatRouteDecision.Option> candidates) { }

    private List<Named> named(String text, IssueNameResolver.Names issueNames) {
        List<Named> named = new ArrayList<>();
        for (var mention : names.mentions(text)) {
            named.add(new Named("company", mention.companies().stream()
                    .map(c -> new ChatRouteDecision.Option(c.id(), c.label())).toList()));
        }
        for (var mention : issueNames.mentions(text)) {
            named.add(new Named("other", mention.issues().stream()
                    .map(i -> new ChatRouteDecision.Option(i.id(), i.label())).toList()));
        }
        return named;
    }

    /** The company or issue a name means: its only candidate, or the one the member picked in a clarification. */
    private static Optional<String> resolved(Named mention, Set<String> chosen) {
        if (mention.candidates().size() == 1) return Optional.of(mention.candidates().getFirst().id());
        List<String> picked = mention.candidates().stream().map(ChatRouteDecision.Option::id).filter(chosen::contains).toList();
        return picked.size() == 1 ? Optional.of(picked.getFirst()) : Optional.empty();
    }

    // ---------------------------------------------------------------- generator

    @Override
    public ChatGeneratedAnswer generate(ChatRun run, ChatBranchContext context) {
        ObjectNode input = StrictJson.newObject();
        input.set("turns", turns(run));
        ArrayNode branches = input.putArray("branches");
        Map<String, Optional<ObjectNode>> quotes = new HashMap<>();
        Set<String> quoted = new LinkedHashSet<>();
        for (ChatBranchContext.Branch branch : context.branches()) {
            ObjectNode wire = branches.addObject().put("requirementId", branch.requirementId()).put("label", branch.label())
                    .put("general", branch.general()).put("noneFound", branch.noneFound());
            ArrayNode items = wire.putArray("items");
            ArrayNode evidence = wire.putArray("evidence");
            Set<String> seen = new HashSet<>();
            Set<String> branchEvidence = new LinkedHashSet<>();
            for (ChatToolResult result : branch.results()) {
                if (!result.succeeded()) continue;
                for (ChatToolItem item : result.items()) {
                    // Only ZOOP's own graph labels travel as items; an evidence item's label is its article's title,
                    // which may reach a model only inside a quote the source's chat grant allows.
                    if (SENT_ITEM_KINDS.contains(item.kind()) && items.size() < MAX_ITEMS && seen.add(item.kind() + ":" + item.id())) {
                        items.addObject().put("id", item.id()).put("kind", item.kind()).put("label", clip(item.label()));
                    }
                    branchEvidence.addAll(item.evidenceIds());
                }
                branchEvidence.addAll(result.evidenceIds());
            }
            Set<String> sent = new HashSet<>();
            for (String id : branchEvidence) {
                if (evidence.size() >= MAX_QUOTES) break;
                if (!quoted.contains(id) && quoted.size() >= Math.min(MAX_QUOTES, context.maxCitations())) continue;
                Optional<ObjectNode> quote = quotes.computeIfAbsent(id, key -> quote(run, key));
                if (quote.isPresent()) {
                    quoted.add(id);
                    sent.add(id);
                    evidence.add(quote.get().deepCopy());
                }
            }
            paths(wire, branch, sent);
        }
        input.put("maxCitations", Math.min(MAX_QUOTES, context.maxCitations()));
        JsonNode answer = call(run, ANSWER, "answer", input);
        return decode(() -> {
            List<ChatGeneratedAnswer.Section> sections = new ArrayList<>();
            for (JsonNode s : array(answer, "sections")) {
                sections.add(new ChatGeneratedAnswer.Section(text(s, "basis"), text(s, "text"), strings(s, "requirementIds"),
                        strings(s, "evidenceIds")));
            }
            return new ChatGeneratedAnswer(sections, strings(answer, "insufficientRequirementIds"),
                    strings(answer, "graphTargetIds"));
        });
    }

    /** The quote the generator may cite, or empty when the evidence cannot be read now or cannot be sent. */
    private Optional<ObjectNode> quote(ChatRun run, String evidenceId) {
        if (!EVIDENCE.matcher(evidenceId).matches()) return Optional.empty();
        return citations.cite(evidenceId, run.graphVersionId(), run.context().asOf(), run.jobId()).flatMap(this::quote);
    }

    private Optional<ObjectNode> quote(Citation citation) {
        if (citation.quote() == null || citation.quote().isEmpty() || citation.quote().length() > MAX_QUOTE) {
            return Optional.empty();
        }
        Optional<String> sourceId;
        if ("company_profile".equals(citation.sourceKind())) {
            // ZOOP's own catalog text: its grant is the catalog's, not an article provider's.
            sourceId = Optional.of(ChatCompanyProfiles.SOURCE_ID);
        } else if ("zoop_doc".equals(citation.sourceKind())) {
            sourceId = Optional.of(ChatZoopDocs.SOURCE_ID);
        } else if ("article".equals(citation.sourceKind()) && citation.articleId() != null) {
            sourceId = sources.sourceOf(citation.articleId());
        } else {
            return Optional.empty();
        }
        return sourceId.map(source -> {
            ObjectNode quote = StrictJson.newObject().put("evidenceId", citation.evidenceId()).put("sourceId", source)
                    .put("quote", citation.quote());
            if (citation.articleTitle() != null && citation.articleTitle().length() <= 500) {
                quote.put("articleTitle", citation.articleTitle());
            }
            if (citation.publishedAt() != null) quote.put("publishedAt", citation.publishedAt().toString());
            return quote;
        });
    }

    // ---------------------------------------------------------------- verifier

    @Override
    public ChatSemanticVerdicts verify(ChatRun run, List<ChatGeneratedAnswer.Section> sections, List<Citation> cited) {
        if (sections.isEmpty()) return new ChatSemanticVerdicts(List.of());
        ObjectNode input = StrictJson.newObject();
        ArrayNode wireSections = input.putArray("sections");
        for (var section : sections) {
            ObjectNode wire = wireSections.addObject().put("basis", section.basis()).put("text", section.text());
            ArrayNode ids = wire.putArray("evidenceIds");
            section.evidenceIds().forEach(ids::add);
        }
        ArrayNode wireCitations = input.putArray("citations");
        for (Citation citation : cited) {
            // A citation that cannot be sent leaves its section without support: the AI side refuses the input.
            wireCitations.add(quote(citation).orElseThrow(() -> new ChatModels.Failure(Fate.REFUSED,
                    "a cited quote cannot be sent for verification")));
        }
        JsonNode answer = call(run, VERIFICATION, "verify", input);
        return decode(() -> {
            List<ChatSemanticVerdicts.Verdict> verdicts = new ArrayList<>();
            for (JsonNode v : array(answer, "sections")) {
                JsonNode support = v.get("support");
                verdicts.add(new ChatSemanticVerdicts.Verdict(support == null || support.isNull() ? null : text(v, "support"),
                        text(v, "prohibitedAdvice")));
            }
            return new ChatSemanticVerdicts(verdicts);
        });
    }

    // ---------------------------------------------------------------- one stage

    private JsonNode call(ChatRun run, String stage, String suffix, ObjectNode input) {
        String invocation = run.jobId() + "." + run.attemptNo() + "." + suffix;
        ChatStageCall request = new ChatStageCall(invocation, stage, mode, input);
        String execution;
        try {
            execution = recorder.start(run.jobId(), run.attemptNo(), stage, mode);
        } catch (RuntimeException unrecorded) {
            throw new ChatModels.Failure(Fate.NOT_SENT, "the model call could not be recorded");
        }
        ChatStageReply reply;
        try {
            reply = client.invoke(request);
        } catch (AiClientException error) {
            Fate fate = fate(error);
            finish(execution, fate == Fate.UNKNOWN ? "unknown" : "failed",
                    fate == Fate.UNKNOWN ? "unknown" : "not_sent", null, code(error));
            throw new ChatModels.Failure(fate, "chat stage " + stage + " failed: " + code(error));
        }
        if (!reply.succeeded()) {
            ChatStageReply.Failure failure = reply.failure();
            Fate fate = failure.unknown() ? Fate.UNKNOWN : failure.sent() ? Fate.NOT_SENT : Fate.REFUSED;
            String sendState = failure.unknown() ? "unknown" : failure.sent() ? "sent" : "not_sent";
            finish(execution, failure.unknown() ? "unknown" : "failed", sendState, reply.receipt(), failure.code());
            throw new ChatModels.Failure(fate, "chat stage " + stage + " failed: " + failure.code());
        }
        finish(execution, "succeeded", "sent", reply.receipt(), null);
        return reply.answer();
    }

    /**
     * The AI service's answer: 502/504 {@code stage_outcome_unknown} may have sent; 503 started nothing (busy or unavailable);
     * any other refusal (409 mode unavailable, 422, 401/403) would refuse the same run again. A transport failure may have sent
     * unless the connection was never established.
     */
    static Fate fate(AiClientException error) {
        if (error instanceof AiServiceRejectionException rejected) {
            int status = rejected.httpStatus();
            if (status == 503) return Fate.NOT_SENT;
            if (status >= 500) return Fate.UNKNOWN;
            return Fate.REFUSED;
        }
        return error.requestMaybeProcessed() ? Fate.UNKNOWN : Fate.NOT_SENT;
    }

    private static String code(AiClientException error) {
        if (error instanceof AiServiceRejectionException rejected) return rejected.code();
        if (error instanceof com.zoop.ai.AiTransportException transport) return transport.failure().name().toLowerCase(java.util.Locale.ROOT);
        return "client_error";
    }

    private void finish(String execution, String status, String sendState, ChatStageReply.Receipt receipt, String code) {
        // A stage the engine cut off is interrupted, before or during this write, and an interrupted thread cannot use its
        // database connection. The outcome is written on a thread of its own, which the cancellation never reaches, and this
        // thread waits for it; an interrupt that arrives meanwhile is kept for after.
        Thread writer = Thread.ofVirtual().name("chat-model-ledger").start(() -> {
            try {
                recorder.finish(execution, status, sendState, receipt, code);
            } catch (RuntimeException unrecorded) {
                // The stage outcome stands; the running row stays as evidence that the call was made.
            }
        });
        boolean interrupted = false;
        while (true) {
            try {
                writer.join();
                break;
            } catch (InterruptedException cutOff) {
                interrupted = true;
            }
        }
        if (interrupted) Thread.currentThread().interrupt();
    }

    /**
     * The pairs a path read reported, each with its own status and its steps in order: a pair cut by the hop limit never
     * looks like one proven unconnected, and a step names only evidence quoted in this branch, so each hop is explained by
     * its own quotes. Sent only when the branch has a path read.
     */
    private static void paths(ObjectNode wire, ChatBranchContext.Branch branch, Set<String> sent) {
        ArrayNode paths = null;
        for (ChatToolResult result : branch.results()) {
            if (!result.succeeded()) continue;
            for (ChatToolPath path : result.paths()) {
                if (paths == null) paths = wire.putArray("paths");
                if (paths.size() >= MAX_PATHS) return;
                ObjectNode p = paths.addObject().put("fromId", path.fromId()).put("toId", path.toId())
                        .put("status", path.status());
                ArrayNode steps = p.putArray("steps");
                for (ChatToolPath.Step step : path.steps()) {
                    ObjectNode s = steps.addObject().put("edgeId", step.edgeId()).put("sourceId", step.sourceId())
                            .put("targetId", step.targetId()).put("relation", step.relation());
                    if (step.role() == null) s.putNull("role");
                    else s.put("role", clip(step.role()));
                    ArrayNode ids = s.putArray("evidenceIds");
                    step.evidenceIds().stream().filter(sent::contains).forEach(ids::add);
                }
            }
        }
    }

    // ---------------------------------------------------------------- wire helpers

    private static ArrayNode turns(ChatRun run) {
        ArrayNode turns = StrictJson.newArray();
        for (ChatRun.Turn turn : run.turns()) {
            ObjectNode wire = turns.addObject().put("text", turn.question());
            if (turn.choiceLabel() != null) wire.put("choiceLabel", turn.choiceLabel());
            else wire.putNull("choiceLabel");
        }
        return turns;
    }

    private static String clip(String label) {
        if (label == null || label.isBlank()) return "-";
        return label.length() <= MAX_LABEL ? label : label.substring(0, MAX_LABEL);
    }

    /** A succeeded stage whose answer does not have the expected shape is a malformed answer the run may repeat. */
    private static <T> T decode(java.util.function.Supplier<T> parser) {
        try {
            return parser.get();
        } catch (RuntimeException malformed) {
            throw new ChatModels.Failure(Fate.NOT_SENT, "malformed stage answer");
        }
    }

    private static List<JsonNode> array(JsonNode node, String name) {
        JsonNode value = node.get(name);
        if (value == null || !value.isArray()) throw new IllegalArgumentException(name);
        List<JsonNode> items = new ArrayList<>();
        value.values().forEach(items::add);
        return items;
    }

    private static List<String> strings(JsonNode node, String name) {
        return array(node, name).stream().map(item -> {
            if (!item.isString()) throw new IllegalArgumentException(name);
            return item.stringValue();
        }).toList();
    }

    private static String text(JsonNode node, String name) {
        JsonNode value = node.get(name);
        if (value == null || !value.isString()) throw new IllegalArgumentException(name);
        return value.stringValue();
    }

    private static double number(JsonNode value) {
        if (value == null || !value.isNumber()) throw new IllegalArgumentException("number");
        return value.doubleValue();
    }

    private static Map<String, Double> probabilities(JsonNode node, String name) {
        JsonNode value = node.get(name);
        if (value == null || !value.isObject()) throw new IllegalArgumentException(name);
        Map<String, Double> map = new HashMap<>();
        for (var entry : value.properties()) map.put(entry.getKey(), number(entry.getValue()));
        return map;
    }
}
