package com.zoop.document.service;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;

import com.zoop.document.DocumentImportException;
import com.zoop.document.DocumentImportFailure;
import com.zoop.document.repository.ArticleRow;
import com.zoop.document.repository.ArtifactRow;
import com.zoop.document.repository.VersionRow;
import com.zoop.document.service.RegistrationOutcome.PointerResult;
import com.zoop.document.service.RegistrationOutcome.Presence;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * The registration decisions against a registry double with real relational semantics. Rollback itself is Spring's and
 * PostgreSQL's: {@link InMemoryDocumentRegistry#transactionally} only reproduces the boundary, and the operator smoke proves
 * the rollback against PostgreSQL.
 */
class DocumentRegistrationServiceTest {
    private static final Instant NOW = Instant.parse("2026-10-14T05:00:00Z");
    private static final Instant FIRST_OBSERVED = Instant.parse("2026-10-14T01:00:00.123456Z");
    private static final Instant LATER_OBSERVED = Instant.parse("2026-10-14T03:00:00Z");
    private static final Instant PUBLISHED = Instant.parse("2026-10-08T00:00:00Z");

    private final InMemoryDocumentRegistry registry = new InMemoryDocumentRegistry();
    private final DocumentRegistrationService service = new DocumentRegistrationService(registry,
            Clock.fixed(NOW, ZoneOffset.UTC));

    private static String version(char digit) {
        return String.valueOf(digit).repeat(64);
    }

    private static RegistrationCommand command(String article, char version, PointerPolicy pointer) {
        return authored(article, version(version), "synthetic-source", ArticleKind.NEWS,
                "text-" + version(version), "artifact-root:extracted_text/text-" + version(version) + ".txt",
                String.valueOf(version).repeat(64), 100, "제목", "https://example.invalid/" + article, PUBLISHED,
                FIRST_OBSERVED, pointer);
    }

    /** The authored form of a command: no declared publisher, a publication instant or none ({@code datetime} / {@code unknown}). */
    private static RegistrationCommand authored(String articleId, String version, String provider, ArticleKind kind,
            String textArtifactId, String storageUri, String sha256, long bytes, String title, String url, Instant publishedAt,
            Instant collectedAt, PointerPolicy pointer) {
        return new RegistrationCommand(articleId, version, provider, kind, textArtifactId, storageUri, sha256, bytes, title, url,
                null, publishedAt, null, publishedAt == null ? "unknown" : "datetime", collectedAt, pointer);
    }

    private static RegistrationCommand withPublisher(RegistrationCommand base, String publisher) {
        return new RegistrationCommand(base.articleId(), base.version(), base.provider(), base.kind(), base.textArtifactId(),
                base.storageUri(), base.sha256(), base.bytes(), base.title(), base.url(), publisher, base.publishedAt(),
                base.publishedDate(), base.publicationPrecision(), base.collectedAt(), base.pointer());
    }

    private RegistrationOutcome register(RegistrationCommand command) {
        return registry.transactionally(() -> service.register(command));
    }

    private DocumentImportException rejected(RegistrationCommand command) {
        return assertThrows(DocumentImportException.class, () -> register(command));
    }

    @Test
    void insertionOnlyCreatesTheIdentityVersionAndArtifactAndLeavesThePointerUnset() {
        RegistrationOutcome outcome = register(command("doc-a", 'a', PointerPolicy.keep()));

        assertEquals(Presence.CREATED, outcome.article());
        assertEquals(Presence.CREATED, outcome.artifact());
        assertEquals(Presence.CREATED, outcome.version());
        assertEquals(PointerResult.UNCHANGED, outcome.pointer());
        assertNull(outcome.currentVersion());
        assertEquals(FIRST_OBSERVED, outcome.collectedAt());

        InMemoryDocumentRegistry.State state = registry.state();
        assertEquals(new ArticleRow("doc-a", "news", "synthetic-source", null, "available"), state.articles().get("doc-a"));
        assertEquals(new ArtifactRow("text-" + version('a'), "extracted_text",
                "artifact-root:extracted_text/text-" + version('a') + ".txt", version('a'), 100,
                "text/plain; charset=utf-8", NOW), state.artifacts().get("text-" + version('a')));
        VersionRow stored = state.versions().values().iterator().next();
        assertEquals("doc-a", stored.articleId());
        assertEquals(version('a'), stored.version());
        assertEquals("제목", stored.title());
        assertNull(stored.publisher());
        assertEquals("https://example.invalid/doc-a", stored.url());
        assertEquals(PUBLISHED, stored.publishedAt());
        assertNull(stored.publishedDate());
        assertEquals("datetime", stored.publicationPrecision());
        assertNull(stored.rawArtifactId());
        assertEquals("text-" + version('a'), stored.textArtifactId());
        assertEquals(FIRST_OBSERVED, stored.collectedAt());
    }

    @Test
    void aMissingPublicationTimeIsUnknownNeverAGuessedDayOrMidnight() {
        RegistrationCommand command = authored("doc-a", version('a'), "synthetic-source", ArticleKind.NEWS,
                "text-" + version('a'), "artifact-root:extracted_text/text-" + version('a') + ".txt", version('a'), 1, "",
                "https://example.invalid/", null, FIRST_OBSERVED, PointerPolicy.keep());

        register(command);

        VersionRow stored = registry.state().versions().values().iterator().next();
        assertEquals("unknown", stored.publicationPrecision());
        assertNull(stored.publishedAt());
        assertNull(stored.publishedDate());
        assertEquals("", stored.title());
    }

    @Test
    void compareAndSetMovesTheUnsetPointerAndAReRunIsAlreadyCurrent() {
        RegistrationOutcome moved = register(command("doc-a", 'a', PointerPolicy.moveFrom(null)));
        assertEquals(PointerResult.MOVED, moved.pointer());
        assertEquals(version('a'), moved.currentVersion());

        InMemoryDocumentRegistry.State before = registry.state();
        RegistrationOutcome again = register(command("doc-a", 'a', PointerPolicy.moveFrom(null)));

        assertEquals(PointerResult.ALREADY_CURRENT, again.pointer());
        assertEquals(version('a'), again.currentVersion());
        assertEquals(Presence.EXISTING, again.article());
        assertEquals(Presence.EXISTING, again.artifact());
        assertEquals(Presence.EXISTING, again.version());
        assertEquals(before, registry.state());
        // Even a re-run whose expectation is now stale is idempotent when the target is already current.
        assertEquals(PointerResult.ALREADY_CURRENT,
                register(command("doc-a", 'a', PointerPolicy.moveFrom(version('z')))).pointer());
    }

    @Test
    void anOutOfOrderReplayNeverMovesThePointerBackwards() {
        register(command("doc-a", 'a', PointerPolicy.moveFrom(null)));
        register(command("doc-a", 'b', PointerPolicy.keep()));
        assertEquals(PointerResult.MOVED, register(command("doc-a", 'b', PointerPolicy.moveFrom(version('a')))).pointer());

        // The replay of version a, observed later, without an explicit pointer request: no change.
        RegistrationCommand replay = authored("doc-a", version('a'), "synthetic-source", ArticleKind.NEWS,
                "text-" + version('a'), "artifact-root:extracted_text/text-" + version('a') + ".txt", version('a'), 100,
                "제목", "https://example.invalid/replayed-url", PUBLISHED, LATER_OBSERVED, PointerPolicy.keep());
        RegistrationOutcome outcome = register(replay);

        assertEquals(Presence.EXISTING, outcome.version());
        assertEquals(PointerResult.UNCHANGED, outcome.pointer());
        assertEquals(version('b'), outcome.currentVersion());
        // The first registered observation's values are kept; the later URL and time are not applied.
        assertEquals(FIRST_OBSERVED, outcome.collectedAt());
        assertEquals("https://example.invalid/doc-a", registry.state().versions().get("doc-a\u0000" + version('a')).url());

        // The replay with an explicit expectation that no longer holds is a conflict that reports the actual pointer.
        DocumentImportException stale = rejected(command("doc-a", 'a', PointerPolicy.moveFrom(version('c'))));
        assertEquals(DocumentImportFailure.CURRENT_VERSION_CONFLICT, stale.failure());
        assertTrue(stale.hasCurrentVersion());
        assertEquals(version('b'), stale.currentVersion());
        assertEquals(version('b'), registry.state().articles().get("doc-a").currentVersion());
    }

    @Test
    void aStaleExpectationFailsWithTheActualPointerAndUndoesWhatTheItemWrote() {
        register(command("doc-a", 'a', PointerPolicy.moveFrom(null)));
        InMemoryDocumentRegistry.State before = registry.state();

        // A new version b with a wrong expectation: the conflict comes after b was inserted, so it must all roll back.
        DocumentImportException wrongVersion = rejected(command("doc-a", 'b', PointerPolicy.moveFrom(version('x'))));
        assertEquals(DocumentImportFailure.CURRENT_VERSION_CONFLICT, wrongVersion.failure());
        assertEquals(version('a'), wrongVersion.currentVersion());
        assertEquals(before, registry.state());

        DocumentImportException expectedNull = rejected(command("doc-a", 'b', PointerPolicy.moveFrom(null)));
        assertEquals(version('a'), expectedNull.currentVersion());
        assertEquals(before, registry.state());

        // An unset pointer reported as such is a null value, not an absent one.
        register(command("doc-n", 'n', PointerPolicy.keep()));
        DocumentImportException unset = rejected(command("doc-n", 'n', PointerPolicy.moveFrom(version('q'))));
        assertTrue(unset.hasCurrentVersion());
        assertNull(unset.currentVersion());
    }

    @Test
    void theArticleMustMatchProviderAndKindAndBeAvailable() {
        registry.seedArticle("doc-a", "news", "another-source", null, "available");
        assertEquals(DocumentImportFailure.ARTICLE_PROVIDER_CONFLICT,
                rejected(command("doc-a", 'a', PointerPolicy.keep())).failure());

        registry.seedArticle("doc-b", "disclosure", "synthetic-source", null, "available");
        assertEquals(DocumentImportFailure.ARTICLE_KIND_CONFLICT,
                rejected(command("doc-b", 'b', PointerPolicy.keep())).failure());

        assertTrue(registry.state().versions().isEmpty());
        assertTrue(registry.state().artifacts().isEmpty());
    }

    @Test
    void privateAndDeletedArticlesAcceptNothingAndAreNeverResetToAvailable() {
        for (String access : new String[] {"private", "deleted"}) {
            registry.seedArticle("doc-" + access, "news", "synthetic-source", null, access);
            InMemoryDocumentRegistry.State before = registry.state();

            DocumentImportException denied = rejected(command("doc-" + access, 'a', PointerPolicy.moveFrom(null)));

            assertEquals(DocumentImportFailure.ARTICLE_ACCESS_UNAVAILABLE, denied.failure(), access);
            assertEquals(before, registry.state());
            assertEquals(access, registry.state().articles().get("doc-" + access).accessStatus());
        }
        // An article that was registered while available and later made private takes no new version or pointer move.
        register(command("doc-c", 'c', PointerPolicy.moveFrom(null)));
        registry.setAccessStatus("doc-c", "private");
        InMemoryDocumentRegistry.State before = registry.state();
        assertEquals(DocumentImportFailure.ARTICLE_ACCESS_UNAVAILABLE,
                rejected(command("doc-c", 'd', PointerPolicy.moveFrom(version('c')))).failure());
        assertEquals(DocumentImportFailure.ARTICLE_ACCESS_UNAVAILABLE,
                rejected(command("doc-c", 'c', PointerPolicy.keep())).failure());
        assertEquals(before, registry.state());
    }

    @Test
    void anExistingVersionMustMatchEverythingBoundToIt() {
        register(command("doc-a", 'a', PointerPolicy.keep()));
        InMemoryDocumentRegistry.State before = registry.state();

        RegistrationCommand base = command("doc-a", 'a', PointerPolicy.keep());
        RegistrationCommand otherTitle = authored(base.articleId(), base.version(), base.provider(),
                base.kind(), base.textArtifactId(), base.storageUri(), base.sha256(), base.bytes(), "다른 제목", base.url(),
                base.publishedAt(), base.collectedAt(), base.pointer());
        RegistrationCommand otherPublished = authored(base.articleId(), base.version(), base.provider(),
                base.kind(), base.textArtifactId(), base.storageUri(), base.sha256(), base.bytes(), base.title(), base.url(),
                PUBLISHED.plusSeconds(1), base.collectedAt(), base.pointer());
        RegistrationCommand noPublished = authored(base.articleId(), base.version(), base.provider(),
                base.kind(), base.textArtifactId(), base.storageUri(), base.sha256(), base.bytes(), base.title(), base.url(),
                null, base.collectedAt(), base.pointer());

        for (RegistrationCommand changed : new RegistrationCommand[] {otherTitle, otherPublished, noPublished}) {
            assertEquals(DocumentImportFailure.VERSION_CONFLICT, rejected(changed).failure());
        }
        assertEquals(before, registry.state());
    }

    @Test
    void aDayPrecisionVersionKeepsTheDateAndConflictsWithAnyOtherPrecision() {
        RegistrationCommand base = command("doc-a", 'a', PointerPolicy.keep());
        java.time.LocalDate day = java.time.LocalDate.of(2026, 10, 14);
        RegistrationCommand dated = new RegistrationCommand(base.articleId(), base.version(), base.provider(), base.kind(),
                base.textArtifactId(), base.storageUri(), base.sha256(), base.bytes(), base.title(), base.url(), null, null, day,
                "day",
                base.collectedAt(), base.pointer());

        register(dated);
        VersionRow stored = registry.state().versions().values().iterator().next();
        assertNull(stored.publishedAt());
        assertEquals(day, stored.publishedDate());
        assertEquals("day", stored.publicationPrecision());
        assertEquals(Presence.EXISTING, register(dated).version());

        // The same version arriving as an instant, as unknown, or with another day is a different record, never a silent update.
        RegistrationCommand instant = base;
        RegistrationCommand unknown = new RegistrationCommand(base.articleId(), base.version(), base.provider(), base.kind(),
                base.textArtifactId(), base.storageUri(), base.sha256(), base.bytes(), base.title(), base.url(), null, null, null,
                "unknown", base.collectedAt(), base.pointer());
        RegistrationCommand otherDay = new RegistrationCommand(base.articleId(), base.version(), base.provider(), base.kind(),
                base.textArtifactId(), base.storageUri(), base.sha256(), base.bytes(), base.title(), base.url(), null, null,
                day.plusDays(1), "day", base.collectedAt(), base.pointer());
        for (RegistrationCommand changed : new RegistrationCommand[] {instant, unknown, otherDay}) {
            assertEquals(DocumentImportFailure.VERSION_CONFLICT, rejected(changed).failure());
        }
    }

    @Test
    void observationLocalValuesAreNeitherComparedNorUpdated() {
        register(command("doc-a", 'a', PointerPolicy.keep()));
        RegistrationCommand base = command("doc-a", 'a', PointerPolicy.keep());
        RegistrationCommand laterObservation = authored(base.articleId(), base.version(), base.provider(),
                base.kind(), base.textArtifactId(), base.storageUri(), base.sha256(), base.bytes(), base.title(),
                "https://example.invalid/another", base.publishedAt(), LATER_OBSERVED, base.pointer());

        RegistrationOutcome outcome = register(laterObservation);

        assertEquals(Presence.EXISTING, outcome.version());
        assertEquals(FIRST_OBSERVED, outcome.collectedAt());
        VersionRow stored = registry.state().versions().values().iterator().next();
        assertEquals("https://example.invalid/doc-a", stored.url());
        assertEquals(FIRST_OBSERVED, stored.collectedAt());
    }

    @Test
    void anExistingArtifactMustMatchAndAStorageUriIsNeverShared() {
        register(command("doc-a", 'a', PointerPolicy.keep()));
        InMemoryDocumentRegistry.State before = registry.state();
        RegistrationCommand base = command("doc-a", 'a', PointerPolicy.keep());

        RegistrationCommand otherHash = authored(base.articleId(), base.version(), base.provider(),
                base.kind(), base.textArtifactId(), base.storageUri(), version('f'), base.bytes(), base.title(), base.url(),
                base.publishedAt(), base.collectedAt(), base.pointer());
        RegistrationCommand otherSize = authored(base.articleId(), base.version(), base.provider(),
                base.kind(), base.textArtifactId(), base.storageUri(), base.sha256(), base.bytes() + 1, base.title(),
                base.url(), base.publishedAt(), base.collectedAt(), base.pointer());
        RegistrationCommand otherUri = authored(base.articleId(), base.version(), base.provider(),
                base.kind(), base.textArtifactId(), "artifact-root:extracted_text/elsewhere.txt", base.sha256(),
                base.bytes(), base.title(), base.url(), base.publishedAt(), base.collectedAt(), base.pointer());
        for (RegistrationCommand changed : new RegistrationCommand[] {otherHash, otherSize, otherUri}) {
            assertEquals(DocumentImportFailure.ARTIFACT_CONFLICT, rejected(changed).failure());
        }
        assertEquals(before, registry.state());

        // A different document claiming the same URI is refused even though its identity is new.
        RegistrationCommand sameUri = authored("doc-b", version('b'), "synthetic-source", ArticleKind.NEWS,
                "text-" + version('b'), base.storageUri(), version('b'), 1, "t", "https://example.invalid/b", PUBLISHED,
                FIRST_OBSERVED, PointerPolicy.keep());
        assertEquals(DocumentImportFailure.ARTIFACT_CONFLICT, rejected(sameUri).failure());
        assertEquals(before, registry.state());
    }

    @Test
    void twoSourcesWithTheSameBytesKeepSeparateIdentitiesAndArtifacts() {
        RegistrationCommand first = authored("doc-s1", version('1'), "source-one", ArticleKind.NEWS,
                "text-" + version('1'), "artifact-root:extracted_text/text-" + version('1') + ".txt", version('e'), 42,
                "t", "https://one.invalid/a", PUBLISHED, FIRST_OBSERVED, PointerPolicy.moveFrom(null));
        RegistrationCommand second = authored("doc-s2", version('2'), "source-two", ArticleKind.DISCLOSURE,
                "text-" + version('2'), "artifact-root:extracted_text/text-" + version('2') + ".txt", version('e'), 42,
                "t", "https://two.invalid/a", null, LATER_OBSERVED, PointerPolicy.keep());

        register(first);
        register(second);

        InMemoryDocumentRegistry.State state = registry.state();
        assertEquals(2, state.articles().size());
        assertEquals(2, state.artifacts().size());
        assertEquals(2, state.versions().size());
        assertEquals("source-one", state.articles().get("doc-s1").provider());
        assertEquals("source-two", state.articles().get("doc-s2").provider());
        assertEquals(version('e'), state.artifacts().get("text-" + version('1')).sha256());
        assertEquals(version('e'), state.artifacts().get("text-" + version('2')).sha256());
        assertFalse(state.artifacts().get("text-" + version('1')).storageUri()
                .equals(state.artifacts().get("text-" + version('2')).storageUri()));
        assertEquals(version('1'), state.articles().get("doc-s1").currentVersion());
        assertNull(state.articles().get("doc-s2").currentVersion());
    }

    @Test
    void aDeclaredPublisherIsStoredExactlyAndAReImportOfTheSameVersionIsIdempotent() {
        String publisher = "  합성일보 \uD83D\uDE00 ";
        RegistrationCommand declared = withPublisher(command("doc-a", 'a', PointerPolicy.keep()), publisher);

        assertEquals(Presence.CREATED, register(declared).version());
        assertEquals(publisher, registry.state().versions().values().iterator().next().publisher());

        InMemoryDocumentRegistry.State before = registry.state();
        RegistrationOutcome replay = register(declared);
        assertEquals(Presence.EXISTING, replay.version());
        assertEquals(before, registry.state());
    }

    @Test
    void thePublisherIsBoundToTheVersionSoNoOtherValueOrAbsenceMayReuseIt() {
        RegistrationCommand base = command("doc-a", 'a', PointerPolicy.keep());
        register(withPublisher(base, "합성일보"));
        InMemoryDocumentRegistry.State declaredState = registry.state();

        // A different outlet, a different spelling and the absence of any outlet are three other records, never an update.
        for (String changed : new String[] {"합성경제", "합성일보 ", null}) {
            assertEquals(DocumentImportFailure.VERSION_CONFLICT, rejected(withPublisher(base, changed)).failure(),
                    "publisher " + changed);
        }
        assertEquals(declaredState, registry.state());
    }

    @Test
    void anOlderVersionWithoutAPublisherStaysImmutableAndANewDeclarationNeverBackfillsIt() {
        RegistrationCommand base = command("doc-a", 'a', PointerPolicy.keep());
        register(base);
        InMemoryDocumentRegistry.State before = registry.state();

        assertEquals(DocumentImportFailure.VERSION_CONFLICT, rejected(withPublisher(base, "합성일보")).failure());
        assertEquals(before, registry.state());
        assertNull(registry.state().versions().values().iterator().next().publisher());

        // The unchanged NULL-publisher record still re-imports; a publisher-bearing observation is another version (another
        // documentVersion in the ledger) and registers next to it without touching it.
        assertEquals(Presence.EXISTING, register(base).version());
        RegistrationCommand declared = withPublisher(command("doc-a", 'b', PointerPolicy.keep()), "합성일보");
        assertEquals(Presence.CREATED, register(declared).version());
        assertNull(registry.state().versions().get("doc-a\u0000" + version('a')).publisher());
        assertEquals("합성일보", registry.state().versions().get("doc-a\u0000" + version('b')).publisher());
    }
}
