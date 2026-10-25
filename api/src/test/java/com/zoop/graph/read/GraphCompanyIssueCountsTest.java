package com.zoop.graph.read;

import static com.zoop.graph.read.GraphReadFixtures.HANMI;
import static com.zoop.graph.read.GraphReadFixtures.HBM_EQUIP;
import static com.zoop.graph.read.GraphReadFixtures.HYNIX;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.Test;

class GraphCompanyIssueCountsTest {
    private static final Instant NOW = Instant.parse("2026-10-16T12:00:00Z");
    private static final String TSMC = "NYSE:TSM";
    private DisclosureExclusions exclusions = DisclosureExclusions.NONE;
    private final GraphCompanyIssueCounts counts = new GraphCompanyIssueCounts(GraphReadFixtures.reader(NOW, pinned -> exclusions));

    @Test
    void countsDistinctLinkedIssuesInTheActiveVersion() {
        var snapshot = counts.countIssues(List.of(HYNIX, TSMC, "ORG:OPENAI"), null, null, false);
        assertEquals("fixture-2026-10-08", snapshot.graphVersion());
        assertEquals(NOW, snapshot.asOf());
        assertEquals(Map.of(HYNIX, 2L, TSMC, 2L, "ORG:OPENAI", 0L), snapshot.counts());
    }

    @Test
    void requestedAsOfPinsTheVersionActiveThen() {
        Instant asOf = Instant.parse("2026-10-05T00:00:00Z");
        var snapshot = counts.countIssues(List.of(TSMC), null, asOf, true);
        assertEquals("fixture-2026-10-01", snapshot.graphVersion());
        assertEquals(asOf, snapshot.asOf());
        assertEquals(1L, snapshot.counts().get(TSMC));
    }

    @Test
    void aLaterPageWithAPinnedReadTimeCountsLikeTheFirstPage() {
        // Page two echoes page one's read time; it must not turn into an asOf filter.
        var first = counts.countIssues(List.of(HYNIX), null, null, false);
        var second = counts.countIssues(List.of(HYNIX), first.graphVersion(), first.asOf(), false);
        assertEquals(first, second);
    }

    @Test
    void currentExclusionsLowerTheCount() {
        exclusions = new DisclosureExclusions(1, Set.of(HBM_EQUIP), Set.of(), Set.of());
        assertEquals(0L, counts.countIssues(List.of(HANMI), null, null, false).counts().get(HANMI));
    }

    @Test
    void noPublicVersionIsSourceUnavailableBecauseSearchHasNo409() {
        var error = assertThrows(CustomException.class,
                () -> counts.countIssues(List.of(HYNIX), null, Instant.parse("2026-09-01T00:00:00Z"), true));
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, error.getErrorCode());
    }
}
