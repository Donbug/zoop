package com.zoop.chat.orchestrator;

import com.zoop.chat.dto.GraphTarget;
import com.zoop.chat.orchestrator.ChatBranchContext.Branch;
import com.zoop.chat.tool.ChatToolItem;
import com.zoop.chat.tool.ChatToolResult;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * Layer 1 of output validation (design summary 8.2): deterministic checks by check id, no model. Any failure ends the job
 * as {@code validation_failed} before the semantic verifier is called. Quote text and offsets are not checked here because
 * the generator never supplies them: the server builds every citation from the evidence record itself.
 *
 * <ul>
 * <li>{@code schema}: at most 12 sections with a known basis, text and requirements; at most 20 distinct evidence ids each.</li>
 * <li>{@code coverage}: every answerable requirement is in a section or declared insufficient, never both; a limited or
 * unknown requirement is in neither.</li>
 * <li>{@code general_section}: a {@code general_knowledge} section cites nothing, answers pure Q02 requirements only and
 * states no current fact: no amount, percentage, price, year or calendar date (design summary 8.2: Q02 is never a way around
 * a lookup).</li>
 * <li>{@code evidence_section}: an {@code evidence_grounded} section cites only evidence its own requirements' tool results
 * passed on, and cites some unless all its requirements found nothing.</li>
 * <li>{@code citation_budget}: all sections together cite at most 20 distinct evidence ids ({@code ChatResult.citations}).</li>
 * <li>{@code graph_targets}: at most 50, each a company or issue a tool returned.</li>
 * <li>{@code length}: the joined answer, general notice included, is at most 12,000 characters.</li>
 * <li>{@code investment_wording}: no buy/sell recommendation wording (the verifier's {@code prohibitedAdvice} checks again).</li>
 * </ul>
 */
final class ChatAnswerCheck {
    static final String GENERAL_NOTICE = "일반 개념 설명입니다. 최신 기업·시장 사실은 별도 조회가 필요합니다.";
    static final int MAX_SECTIONS = 12;
    static final int MAX_SECTION_EVIDENCE = 20;
    /** Distinct evidence one answer cites at most. */
    static final int MAX_CITATIONS = 20;
    static final int MAX_GRAPH_TARGETS = 50;
    static final int MAX_ANSWER = 12_000;
    private static final Set<String> BASES = Set.of("general_knowledge", "evidence_grounded");
    /** Current-fact markers a general explanation must not carry. */
    private static final Pattern CURRENT_FACT = Pattern.compile(
            "\\d[\\d,.]*\\s*(%|퍼센트|원|달러|엔|위안|억|조|만\\s*원|USD|KRW|bp)|[$₩€¥]\\s*\\d|(19|20)\\d{2}\\s*년"
                    + "|\\d{1,2}\\s*월\\s*\\d{1,2}\\s*일|\\d{4}-\\d{2}-\\d{2}|(최근|오늘|어제|올해|작년|이번 분기|지난 분기)");
    private static final Pattern ADVICE = Pattern.compile(
            "(매수|매도|사|팔|담으)(하)?(세요|십시오|는 것을 추천|기를 권)|추천 종목|목표\\s*주가|지금이 (매수|매도) (적기|타이밍)");

    /** The checked answer: sections with the notice in place, the declared insufficient requirements and map targets. */
    record Passed(List<ChatGeneratedAnswer.Section> sections, List<String> insufficient, List<GraphTarget> graphTargets) { }

    /** The first failing check id, or the passed answer. */
    record Result(Passed passed, String failedCheck) {
        static Result fail(String check) {
            return new Result(null, check);
        }
    }

    private ChatAnswerCheck() {
    }

    static Result check(List<Branch> branches, ChatGeneratedAnswer answer) {
        Map<String, Branch> byId = new HashMap<>();
        branches.forEach(b -> byId.put(b.requirementId(), b));
        if (answer.sections().size() > MAX_SECTIONS) return Result.fail("schema");
        for (var section : answer.sections()) {
            if (!BASES.contains(section.basis()) || section.text() == null || section.text().isBlank()
                    || section.requirementIds().isEmpty() || section.evidenceIds().size() > MAX_SECTION_EVIDENCE
                    || new HashSet<>(section.evidenceIds()).size() != section.evidenceIds().size()
                    || new HashSet<>(section.requirementIds()).size() != section.requirementIds().size()) {
                return Result.fail("schema");
            }
        }

        Set<String> answered = new LinkedHashSet<>();
        answer.sections().forEach(s -> answered.addAll(s.requirementIds()));
        Set<String> insufficient = new LinkedHashSet<>(answer.insufficientRequirementIds());
        if (insufficient.size() != answer.insufficientRequirementIds().size()
                || !byId.keySet().containsAll(answered) || !byId.keySet().containsAll(insufficient)) {
            return Result.fail("coverage");
        }
        for (String id : byId.keySet()) {
            if (answered.contains(id) == insufficient.contains(id)) return Result.fail("coverage");
        }

        List<ChatGeneratedAnswer.Section> sections = new ArrayList<>();
        for (var section : answer.sections()) {
            List<Branch> owners = section.requirementIds().stream().map(byId::get).toList();
            if ("general_knowledge".equals(section.basis())) {
                if (!section.evidenceIds().isEmpty() || owners.stream().anyMatch(b -> !b.general())
                        || CURRENT_FACT.matcher(section.text()).find()) {
                    return Result.fail("general_section");
                }
                String text = section.text().strip();
                sections.add(new ChatGeneratedAnswer.Section(section.basis(),
                        text.startsWith(GENERAL_NOTICE) ? text : GENERAL_NOTICE + " " + text, section.requirementIds(),
                        List.of()));
            } else {
                Set<String> passedOn = new HashSet<>();
                owners.forEach(b -> b.results().forEach(r -> passedOn.addAll(r.evidenceIds())));
                boolean nothingFound = owners.stream().allMatch(Branch::noneFound);
                if (owners.stream().anyMatch(Branch::general) || !passedOn.containsAll(section.evidenceIds())
                        || (section.evidenceIds().isEmpty() && !nothingFound)) {
                    return Result.fail("evidence_section");
                }
                sections.add(section);
            }
        }

        Set<String> cited = new HashSet<>();
        sections.forEach(s -> cited.addAll(s.evidenceIds()));
        if (cited.size() > MAX_CITATIONS) return Result.fail("citation_budget");

        if (answer.graphTargetIds().size() > MAX_GRAPH_TARGETS) return Result.fail("graph_targets");
        Map<String, String> returned = new HashMap<>();
        for (Branch b : branches) {
            for (ChatToolResult r : b.results()) {
                for (ChatToolItem item : r.items()) {
                    if ("company".equals(item.kind()) || "issue".equals(item.kind())) returned.put(item.id(), item.kind());
                }
            }
        }
        List<GraphTarget> targets = new ArrayList<>();
        for (String id : new LinkedHashSet<>(answer.graphTargetIds())) {
            if (!returned.containsKey(id)) return Result.fail("graph_targets");
            targets.add(new GraphTarget(id, returned.get(id)));
        }

        if (joined(sections).length() > MAX_ANSWER) return Result.fail("length");
        if (sections.stream().anyMatch(s -> ADVICE.matcher(s.text()).find())) return Result.fail("investment_wording");
        return new Result(new Passed(List.copyOf(sections), List.copyOf(insufficient), List.copyOf(targets)), null);
    }

    /** The public answer: section texts in order. */
    static String joined(List<ChatGeneratedAnswer.Section> sections) {
        return String.join("\n\n", sections.stream().map(ChatGeneratedAnswer.Section::text).toList());
    }
}
