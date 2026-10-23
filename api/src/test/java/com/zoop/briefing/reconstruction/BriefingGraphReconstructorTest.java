package com.zoop.briefing.reconstruction;

import com.zoop.briefing.storage.*;
import com.zoop.common.json.StrictJson;
import com.zoop.graph.snapshot.*;
import java.time.*;
import java.util.*;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class BriefingGraphReconstructorTest {
    private static final Instant CUTOFF = Instant.parse("2026-10-08T00:20:00Z");
    private BriefingRound row() {
        var payload = StrictJson.newObject();
        var item = payload.putArray("items").addObject().put("eventId", "saved-issue").put("title", "저장된 이슈")
                .put("timePrecision", "unknown").putNull("eventTime");
        item.putArray("evidenceIds").add("saved-evidence");
        item.putArray("companies").addObject().put("id", "KRX:005930").put("name", "삼성전자")
                .put("role", "확정하지 않은 역할").put("roleUnconfirmed", true).put("relationType", "INVOLVES");
        return new BriefingRound("original-round", LocalDate.of(2026,10,8), "morning", CUTOFF, null, CUTOFF, true,
                "published", CUTOFF.plusSeconds(100), CUTOFF.plusSeconds(50), null, payload, StrictJson.newObject(), null);
    }
    private BriefingRoundRepository.ItemEvidence source(Instant at) {
        return new BriefingRoundRepository.ItemEvidence("saved-evidence", "saved-document", "saved-version", "정확 인용", 5, 10,
                "저장 원문", "발행자", "https://example.invalid/test", at, "news", "a".repeat(64));
    }
    @Test void reconstructionKeepsSavedIdentityAndUnknownsWithoutClaimingAnOriginalGraph() {
        var row = row(); String id = BriefingGraphReconstruction.id(row);
        var bytes = com.zoop.common.json.Canonical.appBytes(BriefingGraphReconstructor.build(row, id, Map.of("saved-evidence", source(CUTOFF))));
        var graph = GraphSnapshotCodec.readReconstruction(bytes, id);
        assertEquals("saved-issue", graph.issues().getFirst().issueId());
        assertEquals("KRX:005930", graph.companies().getFirst().companyId());
        assertNull(graph.issues().getFirst().geography());
        assertNull(graph.issues().getFirst().eventTime());
        assertNull(graph.relations().getFirst().role());
        assertEquals(5, graph.evidence().getFirst().start());
        assertThrows(GraphSnapshotUnavailableException.class, () -> GraphSnapshotCodec.read(bytes, id));
        assertNull(row.graphVersion());
        assertEquals(id, BriefingGraphReconstruction.id(row));
        ((tools.jackson.databind.node.ObjectNode) row.payload()).put("changed", true);
        assertNotEquals(id, BriefingGraphReconstruction.id(row));
    }
    @Test void futureOrMissingEvidenceCannotEnterTheReconstructedRound() {
        var row = row(); String id = BriefingGraphReconstruction.id(row);
        assertThrows(IllegalArgumentException.class, () -> BriefingGraphReconstructor.build(row, id, Map.of()));
        assertThrows(IllegalArgumentException.class, () -> BriefingGraphReconstructor.build(row, id, Map.of("saved-evidence", source(CUTOFF.plusSeconds(1)))));
    }
    @Test void structuralRelationsRequireASavedBasisRatherThanAnInventedSupplyLink() {
        var row = row();
        ((tools.jackson.databind.node.ObjectNode) row.payload().at("/items/0/companies/0")).put("relationType", "STRUCTURALLY_RELATED_TO");
        assertThrows(IllegalArgumentException.class, () -> BriefingGraphReconstructor.build(row, BriefingGraphReconstruction.id(row), Map.of("saved-evidence", source(CUTOFF))));
    }
}
