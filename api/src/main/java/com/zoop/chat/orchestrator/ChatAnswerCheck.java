package com.zoop.chat.orchestrator;

import com.zoop.chat.dto.GraphTarget;
import com.zoop.chat.orchestrator.ChatBranchContext.Branch;
import com.zoop.chat.tool.ChatCapability;
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
 * <li>{@code general_names}: a general section answering any requirement the server split off ({@link ChatPlan.Origin})
 * does not name the companies or issues that requirement's parent read returned, whatever else the section answers. A
 * section answering only split-off requirements that breaks this or {@code general_section} is dropped and its
 * requirements count as unanswered: it is the server's addition, not what the member asked, so it does not fail the
 * answer. One that also answers a router requirement fails like any other section, so that requirement is never lost
 * silently.</li>
 * <li>{@code evidence_section}: an {@code evidence_grounded} section cites only evidence its own requirements' tool results
 * passed on, and cites some unless all its requirements found nothing or read only the member's own companies (Q07, which
 * have no public evidence). ZOOP document reads do not count here.</li>
 * <li>{@code document_section}: a {@code zoop_documented} section does the same with what its requirements' ZOOP document
 * reads (Q01) passed on, and nothing else: approved ZOOP text and public evidence never share a section.</li>
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
    private static final Set<String> BASES = Set.of("general_knowledge", "zoop_documented", "evidence_grounded");
    /** Current-fact markers a general explanation must not carry. */
    private static final Pattern CURRENT_FACT = Pattern.compile(
            "\\d[\\d,.]*\\s*(%|퍼센트|원|달러|엔|위안|억|조|만\\s*원|USD|KRW|bp)|[$₩€¥]\\s*\\d|(19|20)\\d{2}\\s*년"
                    + "|\\d{1,2}\\s*월\\s*\\d{1,2}\\s*일|\\d{4}-\\d{2}-\\d{2}|(최근|오늘|어제|올해|작년|이번 분기|지난 분기)");
    private static final Pattern ADVICE = Pattern.compile(
            "(매수|매도|사|팔|담으)(하)?(세요|십시오|는 것을 추천|기를 권)|추천 종목|목표\\s*주가|지금이 (매수|매도) (적기|타이밍)");

    /**
     * The checked answer: sections with the notice in place, the declared insufficient requirements (with those of dropped
     * sections no kept section answers), map targets and the requirements of the general sections dropped.
     */
    record Passed(List<ChatGeneratedAnswer.Section> sections, List<String> insufficient, List<GraphTarget> graphTargets,
            List<String> dropped) { }

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
        Set<String> dropped = new LinkedHashSet<>();
        for (var section : answer.sections()) {
            List<Branch> owners = section.requirementIds().stream().map(byId::get).toList();
            if ("general_knowledge".equals(section.basis())) {
                boolean broken = !section.evidenceIds().isEmpty() || owners.stream().anyMatch(b -> !b.general())
                        || CURRENT_FACT.matcher(section.text()).find();
                boolean named = names(section.text(), owners);
                if (owners.stream().allMatch(b -> b.parent() != null) && (broken || named)) {
                    dropped.addAll(section.requirementIds());
                    continue;
                }
                if (broken) return Result.fail("general_section");
                if (named) return Result.fail("general_names");
                String text = section.text().strip();
                sections.add(new ChatGeneratedAnswer.Section(section.basis(),
                        text.startsWith(GENERAL_NOTICE) ? text : GENERAL_NOTICE + " " + text, section.requirementIds(),
                        List.of()));
            } else {
                boolean documented = "zoop_documented".equals(section.basis());
                Set<String> passedOn = new HashSet<>();
                owners.forEach(b -> b.results().forEach(r -> {
                    if (documentRead(r) == documented) passedOn.addAll(r.evidenceIds());
                }));
                // Nothing found, or only the member's own companies read: neither has public evidence to cite.
                boolean nothingFound = owners.stream().allMatch(b -> b.noneFound() || memberOnly(b));
                if (owners.stream().anyMatch(Branch::general) || !passedOn.containsAll(section.evidenceIds())
                        || (section.evidenceIds().isEmpty() && !nothingFound)) {
                    return Result.fail(documented ? "document_section" : "evidence_section");
                }
                sections.add(section);
            }
        }

        Set<String> kept = new HashSet<>();
        sections.forEach(s -> kept.addAll(s.requirementIds()));
        dropped.stream().filter(id -> !kept.contains(id)).forEach(insufficient::add);

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
        // A dropped section is checked too: advice wording fails the answer wherever it is.
        if (answer.sections().stream().anyMatch(s -> ADVICE.matcher(s.text()).find())) {
            return Result.fail("investment_wording");
        }
        return new Result(new Passed(List.copyOf(sections), List.copyOf(insufficient), List.copyOf(targets),
                List.copyOf(dropped)), null);
    }

    /** Whether the text names a label the owners must avoid, spacing aside. */
    private static boolean names(String text, List<Branch> owners) {
        String flat = text.replaceAll("\\s+", "");
        return owners.stream().flatMap(b -> b.avoidNames().stream()).map(n -> n.replaceAll("\\s+", ""))
                .anyMatch(n -> !n.isEmpty() && flat.contains(n));
    }

    /** A requirement that read only the member's own scope ({@code portfolio.scope.read}), which carries no evidence. */
    static boolean memberOnly(Branch branch) {
        return !branch.results().isEmpty() && branch.results().stream().allMatch(r -> ChatCapability.of(r.capabilityId())
                .map(c -> c == ChatCapability.PORTFOLIO_SCOPE_READ).orElse(false));
    }

    /** A read of ZOOP's own documents: a capability that reads no graph. */
    static boolean documentRead(ChatToolResult result) {
        return ChatCapability.of(result.capabilityId()).map(c -> !c.readsGraph()).orElse(false);
    }

    /** The public answer: section texts in order. */
    static String joined(List<ChatGeneratedAnswer.Section> sections) {
        return String.join("\n\n", sections.stream().map(ChatGeneratedAnswer.Section::text).toList());
    }
}
