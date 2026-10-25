package com.zoop.graph.read;

import static com.zoop.graph.read.GraphReadFixtures.HBM_EQUIP;
import static com.zoop.graph.read.GraphReadFixtures.HBM_SUPPLY;
import static com.zoop.graph.read.GraphReadFixtures.HYNIX;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.company.graph.CompanyGraphReadRequest;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Basis;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

class GraphCompanySnapshotReaderTest {
    private static final Instant NOW = Instant.parse("2026-10-16T12:00:00Z");
    private final GraphCompanySnapshotReader reader =
            new GraphCompanySnapshotReader(GraphReadFixtures.reader(NOW, pinned -> DisclosureExclusions.NONE));

    private com.zoop.company.graph.CompanyGraphSnapshot read(String companyId, Instant asOf) {
        return reader.read(new CompanyGraphReadRequest(companyId, null, null, asOf)).orElseThrow();
    }

    @Test
    void sectionsSplitDirectAndStructuralIssuesWithTheirBasis() {
        var hynix = read(HYNIX, null);
        assertEquals("fixture-2026-10-08", hynix.graphVersion());
        assertTrue(hynix.companyFound());
        assertEquals(List.of(HBM_SUPPLY), hynix.directIssues().stream().map(i -> i.issueId()).toList());
        assertEquals("공급", hynix.directIssues().get(0).role());
        assertEquals(1, hynix.directIssues().get(0).evidenceCount());
        assertTrue(hynix.directIssues().get(0).basis().isEmpty());

        var structural = hynix.structuralIssues().get(0);
        assertEquals(HBM_EQUIP, structural.issueId());
        assertEquals("2026-09-25", structural.eventTime());
        var basis = structural.basis().get(0);
        assertEquals("basis-fixture-04", basis.edgeId());
        assertEquals("SUPPLIES", basis.relationType());
        assertEquals("https://example.invalid/zoop-fixture/art-hbm-equip", basis.sourceUrl());
        assertEquals(List.of("KR"), basis.countries());
        assertEquals("active", basis.validity());
        assertNull(hynix.summary());
    }

    @Test
    void monthPrecisionEventTimeIsKeptAsWritten() {
        assertEquals("2026-09", read("KRX:005930", null).structuralIssues().get(0).eventTime());
    }

    @Test
    void aCompanyOutsideTheVersionIsReportedAsNotFoundInIt() {
        var openai = read("ORG:OPENAI", null);
        assertFalse(openai.companyFound());
        assertTrue(openai.directIssues().isEmpty());
    }

    @Test
    void asOfReadsTheThenActiveVersionAndHidesLaterIssues() {
        var past = read("NYSE:TSM", Instant.parse("2026-10-05T00:00:00Z"));
        assertEquals("fixture-2026-10-01", past.graphVersion());
        assertEquals(1, past.structuralIssues().size());
        assertEquals(ErrorCode.VERSION_UNAVAILABLE, assertThrows(CustomException.class,
                () -> read(HYNIX, Instant.parse("2026-09-01T00:00:00Z"))).getErrorCode());
    }

    @Test
    void basisOfAnArticleNoLongerVisibleHasNoSourceUrl() {
        var basis = new Basis("b", "SUPPLIES", "2026-09-29T00:00:00Z", null, null, List.of(),
                List.of(new PublicGraphSnapshot.ArticleRef("art-x", "v1")));
        assertNull(GraphCompanySnapshotReader.basisOut(basis, Map.of(), NOW).sourceUrl());
    }

    @Test
    void sourceUrlIsTheFirstCitedArticleStillVisible() {
        // The handoff's sourceArticles may name several; one published after asOf is skipped, not a reason for no link.
        var visible = new PublicGraphSnapshot.Article("art-y", "v1", "Y", "https://example.test/y", "2026-09-01");
        var basis = new Basis("b", "SUPPLIES", "2026-09-29T00:00:00Z", null, null, List.of(),
                List.of(new PublicGraphSnapshot.ArticleRef("art-x", "v1"), new PublicGraphSnapshot.ArticleRef("art-y", "v1")));
        assertEquals("https://example.test/y",
                GraphCompanySnapshotReader.basisOut(basis, Map.of("art-y@v1", visible), NOW).sourceUrl());
    }
}
