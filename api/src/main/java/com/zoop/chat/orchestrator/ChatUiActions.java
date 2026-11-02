package com.zoop.chat.orchestrator;

import com.zoop.chat.dto.ChatUiAction;
import com.zoop.chat.dto.ChatUiAction.Target;
import com.zoop.chat.dto.Citation;
import com.zoop.chat.dto.GraphTarget;
import com.zoop.chat.tool.ChatBriefingRound;
import com.zoop.chat.tool.ChatCapability;
import com.zoop.chat.tool.ChatToolPath;
import com.zoop.chat.tool.ChatToolResult;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * The actions of an answer (MCP actions contract 5), derived by the server from the reads of the answered requirements. The
 * model never proposes one, so an id, a route or a label cannot come from it. A company must also be a map target the answer
 * points at: a target is the domain's record of what the answer is about, an action only offers it. A relation and evidence
 * must be what the answer cited for that requirement: an action to open what the answer does not stand on says nothing. A
 * one-step path is its relation, so only the steps of a longer path are offered on their own.
 */
final class ChatUiActions {
    /** Actions beside one answer. */
    static final int MAX = 6;

    private ChatUiActions() {
    }

    private record Draft(String kind, String label, Target target, Set<String> requirements) { }

    /** The articles each requirement's kept sections cite, in citation order: only those open in the evidence window. */
    static Map<String, List<String>> citedArticles(List<ChatGeneratedAnswer.Section> sections, List<Citation> citations) {
        Set<String> articles = new LinkedHashSet<>();
        citations.stream().filter(c -> "article".equals(c.sourceKind())).forEach(c -> articles.add(c.evidenceId()));
        Map<String, Set<String>> cited = new LinkedHashMap<>();
        for (var section : sections) {
            for (String requirement : section.requirementIds()) {
                section.evidenceIds().stream().filter(articles::contains)
                        .forEach(id -> cited.computeIfAbsent(requirement, r -> new LinkedHashSet<>()).add(id));
            }
        }
        Map<String, List<String>> lists = new LinkedHashMap<>();
        cited.forEach((requirement, ids) -> lists.put(requirement, List.copyOf(ids)));
        return lists;
    }

    static List<ChatUiAction> of(List<ChatBranchContext.Branch> branches, Set<String> answered, List<GraphTarget> targets,
            Map<String, List<String>> cited, String graphVersion, Instant asOf) {
        Set<String> companies = new LinkedHashSet<>();
        targets.stream().filter(t -> "company".equals(t.kind())).forEach(t -> companies.add(t.id()));
        Map<Target, Draft> drafts = new LinkedHashMap<>();
        for (var branch : branches) {
            if (!answered.contains(branch.requirementId())) continue;
            Map<String, String> names = new HashMap<>();
            branch.results().forEach(r -> r.items().forEach(i -> names.putIfAbsent(i.id(), i.label())));
            List<String> articles = cited.getOrDefault(branch.requirementId(), List.of());
            for (ChatToolResult result : branch.results()) {
                briefing(result).ifPresent(d -> add(drafts, d, branch.requirementId()));
                if (ChatCapability.PORTFOLIO_SCOPE_READ.id().equals(result.capabilityId()) && !result.items().isEmpty()) {
                    add(drafts, new Draft(ChatUiAction.OPEN_WATCHLIST, "내 종목 보기", Target.watchlist(), new LinkedHashSet<>()),
                            branch.requirementId());
                }
                for (ChatToolPath path : result.paths()) {
                    if (!ChatToolPath.FOUND.equals(path.status())) continue;
                    add(drafts, new Draft(ChatUiAction.FOCUS_PATH, "경로 보기 · " + names.getOrDefault(path.fromId(), path.fromId())
                            + " → " + names.getOrDefault(path.toId(), path.toId()),
                            Target.path(path.fromId(), path.toId(), graphVersion, asOf), new LinkedHashSet<>()),
                            branch.requirementId());
                    if (path.steps().size() < 2) continue;
                    for (ChatToolPath.Step step : path.steps()) {
                        if (step.evidenceIds().stream().noneMatch(articles::contains)) continue;
                        add(drafts, new Draft(ChatUiAction.FOCUS_RELATION, "관계 보기 · "
                                + names.getOrDefault(step.sourceId(), step.sourceId()) + " – "
                                + names.getOrDefault(step.targetId(), step.targetId()),
                                Target.relation(step.edgeId(), graphVersion, asOf), new LinkedHashSet<>()), branch.requirementId());
                    }
                }
                result.items().stream().filter(i -> "company".equals(i.kind()) && companies.contains(i.id()))
                        .forEach(i -> add(drafts, new Draft(ChatUiAction.OPEN_COMPANY, "기업 상세 · " + i.label(),
                                Target.company(i.id()), new LinkedHashSet<>()), branch.requirementId()));
            }
            if (!articles.isEmpty()) {
                add(drafts, new Draft(ChatUiAction.OPEN_EVIDENCE, "근거 보기 · " + articles.size() + "건",
                        Target.evidence(articles, graphVersion, asOf), new LinkedHashSet<>()), branch.requirementId());
            }
        }
        List<ChatUiAction> actions = new ArrayList<>();
        for (Draft draft : drafts.values()) {
            if (actions.size() == MAX) break;
            actions.add(new ChatUiAction("action-" + (actions.size() + 1), draft.kind(), draft.label(),
                    List.copyOf(draft.requirements()), draft.target()));
        }
        return List.copyOf(actions);
    }

    private static void add(Map<Target, Draft> drafts, Draft draft, String requirement) {
        drafts.computeIfAbsent(draft.target(), t -> draft).requirements().add(requirement);
    }

    /** The round a briefing read or a briefing evidence read found issues in; its {@code dataVersion} names it ({@code briefing:<date>:<edition>:<id>}). */
    private static java.util.Optional<Draft> briefing(ChatToolResult result) {
        boolean round = ChatCapability.BRIEFING_READ.id().equals(result.capabilityId())
                || ChatCapability.BRIEFING_EVIDENCE.id().equals(result.capabilityId());
        if (!round || result.items().isEmpty()) {
            return java.util.Optional.empty();
        }
        return ChatBriefingRound.ofDataVersion(result.dataVersion()).map(found -> new Draft(ChatUiAction.OPEN_BRIEFING,
                "브리핑 열기 · " + found.date() + ("morning".equals(found.edition()) ? " 출근" : " 퇴근"),
                Target.briefing(found.date().toString(), found.edition()), new LinkedHashSet<>()));
    }
}
