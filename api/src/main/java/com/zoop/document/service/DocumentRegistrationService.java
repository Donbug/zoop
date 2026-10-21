package com.zoop.document.service;

import java.time.Clock;
import java.time.Instant;
import java.util.Objects;

import com.zoop.document.DocumentImportException;
import com.zoop.document.DocumentImportFailure;
import com.zoop.document.repository.ArticleRow;
import com.zoop.document.repository.ArtifactRow;
import com.zoop.document.repository.DocumentRegistryRepository;
import com.zoop.document.repository.VersionRow;
import com.zoop.document.service.RegistrationOutcome.PointerResult;
import com.zoop.document.service.RegistrationOutcome.Presence;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * Registers one imported document version in a single short transaction: article identity, extracted-text artifact,
 * immutable version and the optional pointer compare-and-set. Nothing external is called inside it.
 *
 * <p>Rows are immutable and idempotent. An existing row must match on everything bound to the version; observation-local
 * values ({@code url}, {@code collected_at}) keep what the first registered observation stored and are neither compared
 * nor updated. Any mismatch throws and the whole item rolls back, including an article or version it created. The service
 * never changes {@code access_status}: an article that is not {@code available} (private, deleted) accepts nothing.
 */
@Service
public class DocumentRegistrationService {
    static final String ARTIFACT_KIND = "extracted_text";
    static final String MEDIA_TYPE = "text/plain; charset=utf-8";
    private static final String AVAILABLE = "available";

    private final DocumentRegistryRepository repository;
    private final Clock clock;

    public DocumentRegistrationService(DocumentRegistryRepository repository, Clock clock) {
        this.repository = repository;
        this.clock = clock;
    }

    @Transactional
    public RegistrationOutcome register(RegistrationCommand command) {
        Instant now = clock.instant();
        boolean articleCreated = repository.insertArticleIfAbsent(command.articleId(), command.kind().wire(),
                command.provider(), now);
        // The row lock serialises every writer of this article until the transaction ends.
        ArticleRow article = repository.lockArticle(command.articleId())
                .orElseThrow(() -> new DocumentImportException(DocumentImportFailure.INTERNAL_ERROR));
        if (!article.provider().equals(command.provider())) {
            throw new DocumentImportException(DocumentImportFailure.ARTICLE_PROVIDER_CONFLICT);
        }
        if (!article.kind().equals(command.kind().wire())) {
            throw new DocumentImportException(DocumentImportFailure.ARTICLE_KIND_CONFLICT);
        }
        if (!AVAILABLE.equals(article.accessStatus())) {
            throw new DocumentImportException(DocumentImportFailure.ARTICLE_ACCESS_UNAVAILABLE);
        }

        boolean artifactCreated = registerArtifact(command, now);
        boolean versionCreated = registerVersion(command);
        VersionRow stored = repository.findVersion(command.articleId(), command.version())
                .orElseThrow(() -> new DocumentImportException(DocumentImportFailure.INTERNAL_ERROR));

        PointerResult pointer = PointerResult.UNCHANGED;
        String current = article.currentVersion();
        PointerPolicy policy = command.pointer();
        if (policy.move()) {
            if (command.version().equals(current)) {
                pointer = PointerResult.ALREADY_CURRENT;
            } else if (repository.movePointer(command.articleId(), policy.expected(), command.version())) {
                pointer = PointerResult.MOVED;
                current = command.version();
            } else {
                // The row is locked, so `current` is the actual pointer that did not match the expectation.
                throw DocumentImportException.currentVersionConflict(current);
            }
        }
        return new RegistrationOutcome(Presence.of(articleCreated), Presence.of(artifactCreated),
                Presence.of(versionCreated), pointer, current, stored.collectedAt());
    }

    private boolean registerArtifact(RegistrationCommand command, Instant now) {
        ArtifactRow wanted = new ArtifactRow(command.textArtifactId(), ARTIFACT_KIND, command.storageUri(),
                command.sha256(), command.bytes(), MEDIA_TYPE, now);
        boolean created;
        try {
            created = repository.insertArtifactIfAbsent(wanted);
        } catch (DuplicateKeyException storageUriTaken) {
            // The id is new but another artifact already owns this URI: URIs are never shared or overwritten.
            throw new DocumentImportException(DocumentImportFailure.ARTIFACT_CONFLICT);
        }
        ArtifactRow stored = repository.findArtifact(command.textArtifactId())
                .orElseThrow(() -> new DocumentImportException(DocumentImportFailure.INTERNAL_ERROR));
        if (!stored.kind().equals(wanted.kind()) || !stored.storageUri().equals(wanted.storageUri())
                || !stored.sha256().equals(wanted.sha256()) || stored.bytes() != wanted.bytes()
                || !stored.mediaType().equals(wanted.mediaType())) {
            throw new DocumentImportException(DocumentImportFailure.ARTIFACT_CONFLICT);
        }
        return created;
    }

    private boolean registerVersion(RegistrationCommand command) {
        // The publisher is the operator-declared outlet carried by the export (NULL when none was declared, as in every older
        // export); the raw artifact is not exported by S2-1, so it stays NULL. Time precision is the export's own: an instant,
        // a calendar date (never a midnight) or nothing.
        VersionRow wanted = new VersionRow(command.articleId(), command.version(), command.title(), command.publisher(),
                command.url(), command.publishedAt(), command.publishedDate(), command.publicationPrecision(), null,
                command.textArtifactId(), command.collectedAt());
        boolean created = repository.insertVersionIfAbsent(wanted);
        VersionRow stored = repository.findVersion(command.articleId(), command.version())
                .orElseThrow(() -> new DocumentImportException(DocumentImportFailure.INTERNAL_ERROR));
        if (!Objects.equals(stored.title(), wanted.title()) || !Objects.equals(stored.publisher(), wanted.publisher())
                || !Objects.equals(stored.publishedAt(), wanted.publishedAt())
                || !Objects.equals(stored.publishedDate(), wanted.publishedDate())
                || !stored.publicationPrecision().equals(wanted.publicationPrecision())
                || !Objects.equals(stored.rawArtifactId(), wanted.rawArtifactId())
                || !stored.textArtifactId().equals(wanted.textArtifactId())) {
            throw new DocumentImportException(DocumentImportFailure.VERSION_CONFLICT);
        }
        return created;
    }
}
