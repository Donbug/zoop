package com.zoop.chat.orchestrator;

import com.zoop.chat.dto.ChatAnswerSection;
import com.zoop.chat.dto.ChatApplied;
import com.zoop.chat.dto.ChatAppliedItem;
import com.zoop.chat.dto.ChatAppliedPeriod;
import com.zoop.chat.dto.ChatChoice;
import com.zoop.chat.dto.ChatLimitation;
import com.zoop.chat.dto.ChatResult;
import com.zoop.chat.dto.Citation;
import com.zoop.chat.dto.GraphTarget;
import com.zoop.chat.executor.ChatRun;
import com.zoop.common.response.Metadata;
import java.time.Instant;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Builds {@code ChatResult}s from server decisions. Every member-facing sentence here (reasons, limitation messages) is a
 * server template keyed by a machine code; a model never writes one. {@code answerBasis} is computed from the sections.
 */
final class ChatResults {
    /** Placeholder the executor replaces with the job's own message id. */
    static final String PENDING_MESSAGE = "pending";

    private static final Map<String, String> REASONS = Map.ofEntries(
            Map.entry("too_many_requirements", "한 번에 답할 수 있는 요구는 6개까지예요. 먼저 알고 싶은 부분만 골라 다시 물어봐 주세요."),
            Map.entry("ambiguous", "질문의 대상이나 기간을 하나로 정하지 못했어요. 어떤 것을 말씀하신 건지 골라 주세요."),
            Map.entry("ambiguous_target", "어떤 기업이나 사건에 대한 질문인지 알려 주세요."),
            Map.entry("plan_over_budget", "질문 범위가 넓어 한 번에 조회할 수 없어요. 대상이나 기간을 좁혀 주세요."),
            Map.entry("checkpoint_excess", "조건에 맞는 대상이 예상보다 많아요. 이어서 볼 대상을 골라 주세요."),
            Map.entry("clarification_limit", "확인 질문을 두 번 했는데도 범위를 정하지 못했어요. 기업 이름과 기간을 구체적으로 적어 새 질문으로 "
                    + "보내 주세요."),
            Map.entry("out_of_scope", "이 질문은 지금 답할 수 있는 범위 밖이에요. 기업과 사건의 연결이나 근거 자료에 대해 물어봐 주세요."),
            Map.entry("investment_advice", "특정 종목의 매수·매도 판단은 제공하지 않아요. 기업과 사건의 연결이나 근거 자료에 대해 물어봐 주세요."),
            Map.entry("graph_unavailable", "공개된 지도 데이터가 아직 없어 근거를 조회할 수 없어요. 일반 개념 질문은 지금도 할 수 있어요."));

    /**
     * Why an insufficient-evidence result answered nothing, by cause code ({@link InsufficientCause}): the first sentence of
     * its reason. A {@link #HINTS} sentence follows it.
     */
    private static final Map<String, String> CAUSES = Map.of(
            "results_truncated", "조회 상한 때문에 일부 자료만 확인해 답을 단정할 수 없었어요.",
            "evidence_held", "근거는 찾았지만 답변 내용이 근거와 맞는지 충분히 확인하지 못해 보여 드리지 않았어요.",
            "nothing_found", "조회한 범위에서 관련된 공개 자료를 찾지 못했어요.",
            "precondition_unmet", "앞 단계에서 찾은 대상이 질문의 조건에 맞지 않아 이어서 확인하지 못했어요.",
            "evidence_insufficient", "관련 항목은 찾았지만 답에 쓸 수 있는 공개 근거가 부족했어요.");

    /** What the member can try next, chosen from the run's own scope, not from what a model said. */
    private static final Map<String, String> HINTS = Map.of(
            "narrowed", "선택한 근거 안에서만 확인했어요. 선택을 해제하고 다시 물으면 더 넓게 찾아볼 수 있어요.",
            "truncated", "대상이나 기간을 좁혀 다시 물어봐 주세요.",
            "period", "기간을 넓히거나 다른 기업·사건을 지목해 다시 물어봐 주세요.",
            "other", "다른 기업이나 사건을 지목하거나, 지도에서 대상을 고른 뒤 다시 물어봐 주세요.");

    private static final Map<String, String> LIMITATIONS = Map.of(
            "investment_advice", "매수·매도 같은 투자 판단은 제공하지 않아요.",
            "precondition_unmet", "앞 단계에서 찾은 대상이 조건에 맞지 않아 이 부분은 답하지 못했어요.",
            "results_truncated", "조회 상한 때문에 일부 자료만 확인해 이 부분은 단정하지 않았어요.",
            "evidence_insufficient", "이 부분은 답에 쓸 공개 근거가 부족했어요.",
            "out_of_scope", "이 부분은 지금 답할 수 있는 범위 밖이에요.");

    /** {@code evidence_insufficient} messages that say why, when the server knows it; otherwise the kind's own. */
    private static final Map<String, String> INSUFFICIENT = Map.of(
            "evidence_held", "이 부분은 답변 내용이 근거와 맞는지 충분히 확인하지 못해 뺐어요.",
            "nothing_found", "이 부분은 조회한 범위에서 관련 자료를 찾지 못했어요.");

    /** Why nothing or a part could not be answered, as the server decided it. */
    enum InsufficientCause {
        RESULTS_TRUNCATED, EVIDENCE_HELD, NOTHING_FOUND, PRECONDITION_UNMET, EVIDENCE_INSUFFICIENT;

        String code() {
            return name().toLowerCase();
        }
    }

    private ChatResults() {
    }

    /** The reason of an insufficient-evidence result: what happened, then what to try. */
    static String insufficientReason(ChatRun run, InsufficientCause cause) {
        String hint = !run.selection().evidenceIds().isEmpty() ? "narrowed"
                : cause == InsufficientCause.RESULTS_TRUNCATED ? "truncated"
                : run.context().period() != null ? "period" : "other";
        return CAUSES.get(cause.code()) + " " + HINTS.get(hint);
    }

    /** An {@code evidence_insufficient} limitation whose message says why when it is known. */
    static ChatLimitation insufficient(InsufficientCause cause, String label) {
        var limitation = limitation("evidence_insufficient", label);
        String message = INSUFFICIENT.get(cause.code());
        return message == null ? limitation : new ChatLimitation(limitation.kind(), limitation.label(), message);
    }

    /**
     * An insufficient-evidence result: no sections, citations or limitations, but the reason says why and
     * {@code applied} shows the companies and issues the reads looked at.
     */
    static ChatResult insufficient(ChatRun run, InsufficientCause cause, List<ChatAppliedItem> companies,
            List<ChatAppliedItem> issues, boolean questionOverrodeContext, Instant now) {
        return new ChatResult("insufficient_evidence", PENDING_MESSAGE, "", List.of(), "none",
                insufficientReason(run, cause), List.of(), List.of(), List.of(),
                applied(run, companies, issues, questionOverrodeContext, now), List.of(), null, List.of(), metadata(run, now));
    }

    static String reason(String code) {
        String text = REASONS.get(code);
        if (text == null) throw new IllegalArgumentException("no reason template for " + code);
        return text;
    }

    static ChatLimitation limitation(String kind, String label) {
        String message = LIMITATIONS.get(kind);
        if (message == null) throw new IllegalArgumentException("no limitation template for " + kind);
        return new ChatLimitation(kind, label.length() > 200 ? label.substring(0, 200) : label, message);
    }

    /** A clarification or guidance result: no sections, citations or limitations. */
    static ChatResult withoutAnswer(ChatRun run, String outcome, String reasonCode, List<ChatChoice> choices, Instant now) {
        return new ChatResult(outcome, PENDING_MESSAGE, "", List.of(), "none", reason(reasonCode), List.of(), List.of(),
                List.of(), applied(run, List.of(), List.of(), false, now), List.copyOf(choices), null, List.of(),
                metadata(run, now));
    }

    static ChatResult answered(ChatRun run, List<ChatGeneratedAnswer.Section> sections, List<Citation> citations,
            List<GraphTarget> targets, List<ChatAppliedItem> companies, List<ChatAppliedItem> issues,
            List<ChatLimitation> limitations, boolean questionOverrodeContext, Instant now) {
        List<ChatAnswerSection> publicSections = sections.stream()
                .map(s -> new ChatAnswerSection(s.basis(), s.text(), s.evidenceIds())).toList();
        Set<String> sources = new LinkedHashSet<>();
        // Sources are articles; a catalog profile quote has none.
        citations.stream().filter(c -> c.articleId() != null).forEach(c -> sources.add(c.articleId()));
        return new ChatResult("answered", PENDING_MESSAGE, ChatAnswerCheck.joined(sections), publicSections,
                answerBasis(sections), null, List.copyOf(sources), List.copyOf(citations), List.copyOf(targets),
                applied(run, companies, issues, questionOverrodeContext, now), List.of(), null, List.copyOf(limitations),
                metadata(run, now));
    }

    /** One basis gives that basis; more than one is {@code mixed}; none is {@code none}. */
    static String answerBasis(List<ChatGeneratedAnswer.Section> sections) {
        Set<String> bases = new LinkedHashSet<>();
        sections.forEach(s -> bases.add(s.basis()));
        return bases.isEmpty() ? "none" : bases.size() == 1 ? bases.iterator().next() : "mixed";
    }

    private static ChatApplied applied(ChatRun run, List<ChatAppliedItem> companies, List<ChatAppliedItem> issues,
            boolean questionOverrodeContext, Instant now) {
        var context = run.context();
        ChatAppliedPeriod period = context.period() == null ? null
                : new ChatAppliedPeriod(context.period().start(), context.period().end(), "context", null);
        return new ChatApplied(List.copyOf(companies), List.copyOf(issues), period, run.graphVersionId(),
                context.asOf() != null ? context.asOf() : now, questionOverrodeContext);
    }

    private static Metadata metadata(ChatRun run, Instant now) {
        return new Metadata("zoop", now, run.graphVersionId(), run.jobId(), false, List.of());
    }
}
