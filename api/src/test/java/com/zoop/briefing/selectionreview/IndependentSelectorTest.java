package com.zoop.briefing.selectionreview;

import java.time.Instant;
import java.time.ZoneId;
import java.util.List;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

import com.zoop.briefing.selection.BriefingCandidateSelector;
import com.zoop.briefing.selection.SelectionInput;
import static com.zoop.briefing.selection.SelectionInput.*;

/**
 * Codex BriefingCandidateSelector에 대한 Muse 독립 테스트.
 *
 * <p>선정 규칙(briefing-selection-v1)의 핵심 경계를 독립적으로 검증한다.
 */
class IndependentSelectorTest {

    private static final ZoneId KST = ZoneId.of("Asia/Seoul");
    private static final Instant MORNING_0920 = Instant.parse("2026-10-15T00:20:00Z");
    private static final Instant T0910 = Instant.parse("2026-10-15T00:10:00Z");
    private static final Instant T0855 = Instant.parse("2026-10-14T23:55:00Z");

    private SelectionInput.Context context() {
        return new SelectionInput.Context(
            "round-1", "morning", MORNING_0920, null, true,
            "graph-v1", 1L, 1L);
    }

    private SelectionInput.Evidence evidence(String id, Instant publishedAt) {
        var grant = new SelectionInput.Grant(
            "grant-1", "rev-1", Check.PASS,
            List.of("quote"), List.of("briefing"), List.of("public"));
        // Synthetic official source; adapted from Muse4268b5e9 for the current SourceKind contract.
        return new SelectionInput.Evidence(
            id, "article-1", "v1", "text-1", "analysis-1",
            SelectionInput.PublicationTime.exact(publishedAt),
            T0910, grant, Check.PASS, true, true, SourceKind.OFFICIAL_AUTHORITY, "lineage-1");
    }

    private SelectionInput.Impact impact(Change change, boolean material,
            boolean marketWideRule, List<String> evidenceIds) {
        return new SelectionInput.Impact(
            change, material, marketWideRule, null,
            "mechanism: rate cut -> discount rate",
            "scope-ref-1", evidenceIds, List.of());
    }

    private SelectionInput.Candidate candidate(String eventId, Novelty novelty,
            SelectionInput.Impact impact, List<SelectionInput.Evidence> evidence) {
        var evIds = evidence.stream().map(SelectionInput.Evidence::id).toList();
        return new SelectionInput.Candidate(
            eventId, "v1", "canon-1", "graph-v1", 1L, 1L,
            Check.PASS, false, novelty, "delta-ref-1", evIds,
            impact, evidence);
    }

    @Test
    void 신규성_NEW_MATERIAL_FACT가_ADDITIONAL_CONFIRMATION보다_앞선다() {
        var ctx = context();
        var ev1 = evidence("ev-1", T0910);
        var ev2 = evidence("ev-2", T0855);

        var c1 = candidate("evt-a", Novelty.NEW_MATERIAL_FACT,
            impact(Change.LOCAL_MATERIAL, true, false, List.of("ev-1")),
            List.of(ev1));
        var c2 = candidate("evt-b", Novelty.ADDITIONAL_CONFIRMATION,
            impact(Change.LOCAL_MATERIAL, true, false, List.of("ev-2")),
            List.of(ev2));

        var input = new SelectionInput(ctx, true, List.of(c2, c1));
        var result = new BriefingCandidateSelector().select(input);

        assertEquals(2, result.selected().size());
        assertEquals("evt-a", result.selected().get(0).eventId());
    }

    @Test
    void REPEAT는_제외된다() {
        var ctx = context();
        var ev = evidence("ev-1", T0910);
        var c = candidate("evt-a", Novelty.REPEAT,
            impact(Change.LOCAL_MATERIAL, true, false, List.of("ev-1")),
            List.of(ev));

        var input = new SelectionInput(ctx, true, List.of(c));
        var result = new BriefingCandidateSelector().select(input);

        assertTrue(result.selected().isEmpty());
    }

    @Test
    void 중요도1_ROUTINE은_핵심에서_제외된다() {
        var ctx = context();
        var ev = evidence("ev-1", T0910);
        var c = candidate("evt-a", Novelty.NEW_MATERIAL_FACT,
            impact(Change.ROUTINE, true, false, List.of("ev-1")),
            List.of(ev));

        var input = new SelectionInput(ctx, true, List.of(c));
        var result = new BriefingCandidateSelector().select(input);

        assertTrue(result.selected().isEmpty());
    }

    @Test
    void COMMON_POLICY_3요건_충족시_중요도3() {
        var ctx = context();
        var ev = evidence("ev-1", T0910);
        var c = candidate("evt-a", Novelty.NEW_MATERIAL_FACT,
            impact(Change.COMMON_POLICY, true, true, List.of("ev-1")),
            List.of(ev));

        var input = new SelectionInput(ctx, true, List.of(c));
        var result = new BriefingCandidateSelector().select(input);

        assertEquals(1, result.selected().size());
        assertEquals(3, result.selected().get(0).importance());
    }

    @Test
    void 입력_순서와_무관하게_같은_결과() {
        var ctx = context();
        var ev1 = evidence("ev-1", T0910);
        var ev2 = evidence("ev-2", T0855);
        var ev3 = evidence("ev-3", T0910);

        var c1 = candidate("evt-c", Novelty.NEW_MATERIAL_FACT,
            impact(Change.COMMON_POLICY, true, true, List.of("ev-1")),
            List.of(ev1));
        var c2 = candidate("evt-a", Novelty.NEW_MATERIAL_FACT,
            impact(Change.LOCAL_MATERIAL, true, false, List.of("ev-2")),
            List.of(ev2));
        var c3 = candidate("evt-b", Novelty.ADDITIONAL_CONFIRMATION,
            impact(Change.LOCAL_MATERIAL, true, false, List.of("ev-3")),
            List.of(ev3));

        var r1 = new BriefingCandidateSelector().select(
            new SelectionInput(ctx, true, List.of(c1, c2, c3)));
        var r2 = new BriefingCandidateSelector().select(
            new SelectionInput(ctx, true, List.of(c3, c1, c2)));

        assertEquals(
            r1.selected().stream().map(d -> d.eventId()).toList(),
            r2.selected().stream().map(d -> d.eventId()).toList());
    }

    @Test
    void 최대_3개까지만_선택된다() {
        var ctx = context();
        var candidates = new java.util.ArrayList<SelectionInput.Candidate>();
        for (int i = 0; i < 5; i++) {
            var ev = evidence("ev-" + i, T0910);
            candidates.add(candidate("evt-" + i, Novelty.NEW_MATERIAL_FACT,
                impact(Change.LOCAL_MATERIAL, true, false, List.of("ev-" + i)),
                List.of(ev)));
        }

        var input = new SelectionInput(ctx, true, candidates);
        var result = new BriefingCandidateSelector().select(input);

        assertEquals(3, result.selected().size());
    }
}
