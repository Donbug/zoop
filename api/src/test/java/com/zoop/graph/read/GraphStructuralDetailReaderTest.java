package com.zoop.graph.read;

import static com.zoop.graph.read.GraphReadFixtures.*;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.json.StrictJson;
import com.zoop.common.json.StrictJson.Obj;
import com.zoop.document.evidence.service.EvidenceService;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Basis;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Relation;
import com.zoop.graph.version.GraphVersionRecord;
import com.zoop.graph.version.SelectedGraphVersion;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.node.ObjectNode;

/** Synthetic producer metadata; real snapshot filtering and relation projection, stubbed receipt/rights boundary. */
class GraphStructuralDetailReaderTest {
    private static final Instant NOW = Instant.parse("2026-10-16T12:00:00Z");
    private static final String VERSION = "fixture-2026-10-08";
    private static final String EDGE = DisplayGraph.edgeId("STRUCTURALLY_RELATED_TO", HBM_EQUIP, HYNIX);
    private final EvidenceService evidence = mock(EvidenceService.class);
    private final GraphStructuralDetailReader reader = new GraphStructuralDetailReader(evidence);
    private PublicGraphSnapshot snapshot;
    private ObjectNode bundle;
    private ObjectNode rawRelation;

    @BeforeEach void setup() {
        snapshot = snapshot(VERSION);
        bundle = StrictJson.newObject();
        bundle.put("schemaVersion", "zoop-graph-handoff-bundle-7");
        var companies = StrictJson.newArray();
        snapshot.companies().forEach(c -> companies.add(StrictJson.newObject().put("id", c.companyId()).put("label", c.label())));
        bundle.set("companies", companies);
        bundle.set("pathCompanies", StrictJson.newArray());
        var spans = StrictJson.newArray();
        snapshot.evidence().forEach(e -> spans.add(StrictJson.newObject().put("id", e.evidenceId())
                .put("articleId", e.articleId()).put("articleVersion", e.articleVersion())));
        bundle.set("evidence", spans);
        Relation r = snapshot.relations().stream().filter(row -> row.relationId().equals("rel-fixture-04")).findFirst().orElseThrow();
        rawRelation = StrictJson.newObject().put("id", r.relationId()).put("type", r.relationType())
                .put("source", r.source()).put("target", r.target());
        var bases = StrictJson.newArray();
        for (Basis b : r.basis()) {
            ObjectNode raw = StrictJson.newObject().put("relationKey", b.basisId()).put("relationType", b.relationType())
                    .put("verifiedAt", b.verifiedAt()).put("validFrom", b.validFrom()).putNull("validUntil")
                    .put("businessScope", "서버 사업").putNull("productScope");
            var countries = StrictJson.newArray(); b.countries().forEach(countries::add); raw.set("countries", countries);
            var articles = StrictJson.newArray(); b.articles().forEach(a -> articles.add(StrictJson.newObject()
                    .put("articleId", a.articleId()).put("articleVersion", a.articleVersion()))); raw.set("sourceArticles", articles);
            var citations = StrictJson.newArray(); r.evidenceIds().forEach(citations::add); raw.set("evidenceIds", citations);
            bases.add(raw);
        }
        rawRelation.set("basis", bases);
        setPath(List.of(HANMI, HYNIX));
        bundle.set("relations", StrictJson.newArray().add(rawRelation));
        when(evidence.graphImportBundle(VERSION, "r")).thenAnswer(invocation -> Obj.of(bundle));
        when(evidence.shownNow(anyString(), nullable(String.class), eq(VERSION), nullable(Instant.class), eq("r"))).thenReturn(true);
    }

    private void setPath(List<String> ids) {
        var companies = StrictJson.newArray(); ids.forEach(companies::add);
        var links = StrictJson.newArray();
        for (int i = 0; i < ids.size() - 1; i++) links.add(StrictJson.newObject()
                .put("supplierCompanyId", ids.get(i + 1)).put("customerCompanyId", ids.get(i)));
        ObjectNode path = StrictJson.newObject().put("status", "complete");
        path.set("companyIds", companies); path.set("links", links); rawRelation.set("structuralPath", path);
    }

    private PublicGraphReader.Pinned pinned(Instant asOf, DisclosureExclusions exclusions) {
        var version = new GraphVersionRecord(VERSION, 1, "snapshot", "artifact", "synthetic", "hash", true);
        return new PublicGraphReader.Pinned(new SelectedGraphVersion(version, asOf == null ? NOW : asOf, asOf != null),
                DisplayGraph.of(GraphSnapshotFilter.apply(snapshot, asOf, exclusions)));
    }
    private com.zoop.graph.read.dto.StructuralDetails read() { return read(null, DisclosureExclusions.NONE); }
    private com.zoop.graph.read.dto.StructuralDetails read(Instant asOf, DisclosureExclusions exclusions) {
        var pinned = pinned(asOf, exclusions);
        return reader.read(pinned, pinned.graph().edges.get(EDGE), null, "r");
    }
    private void twoHops(String middle, String verifiedAt) {
        var first = Obj.of(rawRelation).objects("basis").getFirst();
        ObjectNode second = (ObjectNode) first.node().deepCopy();
        second.put("relationKey", "second-basis").put("verifiedAt", verifiedAt).put("productScope", "메모리");
        rawRelation.set("basis", StrictJson.newArray().add(first.node()).add(second));
        setPath(List.of(HANMI, middle, HYNIX));
        var relations = snapshot.relations().stream().map(r -> {
            if (!r.relationId().equals("rel-fixture-04")) return r;
            Basis b = r.basis().getFirst();
            return new Relation(r.relationId(), r.relationType(), r.source(), r.target(), r.role(), r.assertionStatus(),
                    r.evidenceIds(), List.of(b, new Basis("second-basis", b.relationType(), verifiedAt,
                            b.validFrom(), b.validUntil(), b.countries(), b.articles())));
        }).toList();
        snapshot = new PublicGraphSnapshot(snapshot.snapshotFormat(), snapshot.versionId(), snapshot.sourceBundleId(),
                snapshot.companies(), snapshot.issues(), relations, snapshot.articles(), snapshot.evidence());
    }

    @Test void exposesExactScopeAndSupplierDirectionRatherThanTraversalDirection() {
        var detail = read();
        assertEquals("available", detail.status());
        var path = detail.paths().getFirst();
        assertEquals(List.of(HANMI, HYNIX), path.companies().stream().map(c -> c.id()).toList());
        var link = path.links().getFirst();
        assertEquals(HYNIX, link.supplierCompanyId()); assertEquals(HANMI, link.customerCompanyId());
        assertEquals("서버 사업", link.businessScope()); assertNull(link.productScope());
        assertEquals("active", link.validity());
        assertEquals(Instant.parse("2026-09-29T00:00:00Z"), link.verifiedAt());
        assertFalse(link.evidenceIds().isEmpty());
    }
    @Test void retainsTwoPublicHopsButNeverExposesPrivateIntermediateCompanies() {
        twoHops(NVDA, "2026-09-30T00:00:00Z");
        assertEquals(2, read().paths().getFirst().links().size());
        bundle.set("companies", StrictJson.newArray().add(StrictJson.newObject().put("id", HANMI))
                .add(StrictJson.newObject().put("id", HYNIX)));
        bundle.set("pathCompanies", StrictJson.newArray().add(StrictJson.newObject().put("id", NVDA).put("label", "private")));
        var detail = read();
        assertEquals("unavailable", detail.status()); assertTrue(detail.paths().isEmpty());
        assertFalse(detail.toString().contains(NVDA)); assertFalse(detail.toString().contains("private"));
    }
    @Test void futureBasisCannotBeRecoveredEvenWhenItsCitationIsAlsoDirectlyReadable() {
        twoHops(NVDA, "2026-10-15T00:00:00Z");
        assertEquals("unavailable", read(Instant.parse("2026-10-10T00:00:00Z"), DisclosureExclusions.NONE).status());
        assertEquals("available", read().status());
    }
    @Test void hidesPathWhenTheParticipatingCompanyLinkIsExcluded() {
        assertEquals("unavailable", read(null, new DisclosureExclusions(1, Set.of(), Set.of("rel-fixture-03"), Set.of())).status());
    }
    @Test void currentRightsCanBeRevokedAndRestoredButAnOutageIsNotMissingData() {
        when(evidence.shownNow(anyString(), nullable(String.class), eq(VERSION), nullable(Instant.class), eq("r"))).thenReturn(false);
        assertEquals("unavailable", read().status());
        when(evidence.shownNow(anyString(), nullable(String.class), eq(VERSION), nullable(Instant.class), eq("r"))).thenReturn(true);
        assertEquals("available", read().status());
        when(evidence.shownNow(anyString(), nullable(String.class), eq(VERSION), nullable(Instant.class), eq("r")))
                .thenThrow(new CustomException(ErrorCode.SOURCE_UNAVAILABLE));
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, assertThrows(CustomException.class, this::read).getErrorCode());
    }
    @Test void distinguishesLegacyFromUnsupportedOrCorruptReceipts() {
        for (int v = 1; v <= 4; v++) {
            bundle.put("schemaVersion", "zoop-graph-handoff-bundle-" + v);
            assertEquals("legacy_data", read().reason());
        }
        for (int v = 5; v <= 7; v++) {
            bundle.put("schemaVersion", "zoop-graph-handoff-bundle-" + v);
            assertEquals("available", read().status());
        }
        bundle.put("schemaVersion", "zoop-graph-handoff-bundle-8");
        assertEquals("details_not_available", read().reason());
        bundle.put("schemaVersion", "zoop-graph-handoff-bundle-7");
        rawRelation.put("target", "wrong");
        assertEquals("details_not_available", read().reason());
    }
    @Test void unmappedPathIsNotAnEmptyOrShortenedPath() {
        twoHops(NVDA, "2026-09-30T00:00:00Z");
        rawRelation.set("structuralPath", StrictJson.newObject().put("status", "unavailable").put("reason", "intermediate_company_unmapped"));
        assertEquals("details_not_available", read().reason()); assertTrue(read().paths().isEmpty());
    }
    @Test void rejectsDuplicateRelationsAndWrongBasisArticles() {
        bundle.set("relations", StrictJson.newArray().add(rawRelation).add(rawRelation));
        assertEquals("details_not_available", read().reason());
        bundle.set("relations", StrictJson.newArray().add(rawRelation));
        ((ObjectNode) Obj.of(rawRelation).objects("basis").getFirst().node()).set("sourceArticles", StrictJson.newArray());
        assertEquals("details_not_available", read().reason());
    }
    @Test void passesRoundAndRequestedAsOfToRightsChecks() {
        var pinned = pinned(NOW, DisclosureExclusions.NONE);
        assertEquals("available", reader.read(pinned, pinned.graph().edges.get(EDGE), "round-1", "r").status());
        verify(evidence, atLeastOnce()).shownNow(anyString(), eq("round-1"), eq(VERSION), eq(NOW), eq("r"));
    }
    @Test void keepsMultipleSourceRelationsSeparate() {
        ObjectNode other = (ObjectNode) rawRelation.deepCopy(); other.put("id", "rel-other");
        bundle.set("relations", StrictJson.newArray().add(other).add(rawRelation));
        var relations = new ArrayList<>(snapshot.relations());
        Relation r = relations.stream().filter(row -> row.relationId().equals("rel-fixture-04")).findFirst().orElseThrow();
        relations.add(new Relation("rel-other", r.relationType(), r.source(), r.target(), r.role(), r.assertionStatus(), r.evidenceIds(), r.basis()));
        snapshot = new PublicGraphSnapshot(snapshot.snapshotFormat(), snapshot.versionId(), snapshot.sourceBundleId(), snapshot.companies(),
                snapshot.issues(), relations, snapshot.articles(), snapshot.evidence());
        assertEquals(List.of("rel-fixture-04", "rel-other"), read().paths().stream().map(p -> p.relationId()).toList());
    }
}
