package com.zoop.chat.model;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Optional;

import com.zoop.chat.model.IssueNameResolver.Entry;
import com.zoop.chat.model.IssueNameResolver.Mention;
import com.zoop.chat.tool.ChatToolUnavailable;
import com.zoop.graph.read.DisclosureExclusions;
import com.zoop.graph.read.PublicGraphReader;
import com.zoop.graph.snapshot.FixtureGraphSnapshotStore;
import com.zoop.graph.version.GraphVersionRecord;
import com.zoop.graph.version.GraphVersionRepository;
import com.zoop.graph.version.GraphVersionSelector;
import org.junit.jupiter.api.Test;

/** Issue names in a question (decision of 2026-10-27): a whole title, or both target and action; shared words ask. */
class IssueNameResolverTest {
    private static final Instant EARLY = Instant.parse("2026-09-01T00:00:00Z");
    private static final Entry SUPPLY = new Entry("iss-supply", "차세대 GPU용 HBM 공급 계약", "HBM", "공급 계약", "2026-09-22");
    private static final Entry EQUIP = new Entry("iss-equip", "HBM 생산 장비 증설 발표", "HBM 장비", "증설", "2026-09-25");
    private static final Entry SUPPLY_AGAIN = new Entry("iss-supply-2", "HBM 추가 공급 계약 체결", "HBM", "공급 계약", "2026-10-02");
    private static final Entry NO_FIELDS = new Entry("iss-bare", "AI 가속기 출시", null, null, null);

    @Test
    void targetAndActionNameAnIssueWhateverTheSpacingAndOrder() {
        for (String question : List.of("HBM 공급 계약 사건 알려줘", "hbm공급계약은?", "공급 계약을 맺은 HBM 건")) {
            List<Mention> mentions = IssueNameResolver.match(question, List.of(SUPPLY, EQUIP));
            assertEquals(1, mentions.size(), question);
            assertEquals(List.of(new IssueNameResolver.Issue("iss-supply", SUPPLY.title())), mentions.getFirst().issues());
        }
        assertTrue(IssueNameResolver.match("HBM은 어디에 공급해?", List.of(SUPPLY)).isEmpty(), "one of the two is not enough");
        assertTrue(IssueNameResolver.match("AI 가속기 출시 소식", List.of(NO_FIELDS)).size() == 1, "a title needs no fields");
        assertTrue(IssueNameResolver.match("가속기 출시", List.of(NO_FIELDS)).isEmpty(), "no fields, no pair");
    }

    @Test
    void sharedWordsAreOneMentionWithEveryIssueLabelledByItsTime() {
        List<Mention> mentions = IssueNameResolver.match("HBM 공급 계약 건", List.of(SUPPLY, SUPPLY_AGAIN, EQUIP));
        assertEquals(1, mentions.size());
        Mention shared = mentions.getFirst();
        assertTrue(shared.ambiguous());
        assertEquals(List.of("iss-supply", "iss-supply-2"), shared.issues().stream().map(IssueNameResolver.Issue::id).toList());
        assertEquals("차세대 GPU용 HBM 공급 계약 (2026-09-22)", shared.issues().getFirst().label());
    }

    @Test
    void aWrittenTitleMeansThatIssueAloneAndIssuesAreInOrderOfAppearance() {
        List<Mention> titled = IssueNameResolver.match("HBM 추가 공급 계약 체결 이후 상황", List.of(SUPPLY, SUPPLY_AGAIN));
        assertEquals(1, titled.size());
        assertFalse(titled.getFirst().ambiguous());
        assertEquals("iss-supply-2", titled.getFirst().issues().getFirst().id());

        List<Mention> two = IssueNameResolver.match("HBM 장비 증설과 HBM 공급 계약은 연결돼?", List.of(SUPPLY, EQUIP));
        assertEquals(List.of("iss-equip", "iss-supply"), two.stream().map(m -> m.issues().getFirst().id()).toList());
    }

    @Test
    void theNamesComeFromTheRunsPinnedGraphOnly() {
        var resolver = new IssueNameResolver(reader());
        assertSame(IssueNameResolver.NONE, resolver.at(null, null));
        List<Mention> mentions = resolver.at("fixture-2026-10-08", null).mentions("HBM 공급 계약 사건 알려줘");
        assertEquals(List.of("iss-fixture-hbm-supply"),
                mentions.stream().map(m -> m.issues().getFirst().id()).toList());
        assertThrows(ChatToolUnavailable.class, () -> resolver.at("fixture-unknown", null));
        // A run frozen without an asOf keeps its pin unfiltered; one frozen at a time is filtered there.
        assertTrue(resolver.at("fixture-2026-10-08", EARLY).mentions("HBM 공급 계약 사건 알려줘").isEmpty(),
                "filtered at the frozen time, before the issue was reported");
    }

    private static PublicGraphReader reader() {
        String id = "fixture-2026-10-08";
        byte[] bytes;
        try (var in = IssueNameResolverTest.class.getClassLoader().getResourceAsStream("graph-fixtures/" + id + ".json")) {
            bytes = in.readAllBytes();
        } catch (java.io.IOException e) {
            throw new java.io.UncheckedIOException(e);
        }
        var record = new GraphVersionRecord(id, 1, "fixture", "artifact-" + id, FixtureGraphSnapshotStore.URI_PREFIX + id + ".json",
                FixtureGraphSnapshotStore.sha256(bytes), true);
        GraphVersionRepository versions = new GraphVersionRepository() {
            public Optional<GraphVersionRecord> find(String v) { return Optional.of(record).filter(r -> r.id().equals(v)); }
            public Optional<GraphVersionRecord> active() { return Optional.of(record); }
            public Optional<String> activeVersionIdAt(Instant asOf) { return Optional.of(id); }
            public boolean everActivated(String v) { return id.equals(v); }
            // First published before any fixture issue was reported: a version-only read of it would show none (#88).
            public Optional<Instant> firstActivatedAt(String v) { return everActivated(v) ? Optional.of(EARLY) : Optional.empty(); }
        };
        Clock clock = Clock.fixed(Instant.parse("2026-10-21T03:00:00Z"), ZoneOffset.UTC);
        return new PublicGraphReader(new GraphVersionSelector(versions, clock),
                new FixtureGraphSnapshotStore(IssueNameResolverTest.class.getClassLoader()), pinned -> DisclosureExclusions.NONE);
    }
}
