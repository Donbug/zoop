package com.zoop.graph.publication;

import java.time.Clock;
import java.time.Instant;
import java.util.HashSet;
import java.util.Set;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.json.StrictJson;
import com.zoop.document.evidence.service.DocumentReadSources;
import com.zoop.document.evidence.service.GraphReceiptGrants;
import com.zoop.document.importer.SourceRegistry;
import com.zoop.document.repository.DocumentRegistryRepository;
import com.zoop.graph.publication.GraphPublicationReader.IssueRef;
import com.zoop.graph.publication.GraphPublicationReader.Publication;
import com.zoop.graph.read.DisclosureExclusionReader;
import com.zoop.graph.read.DisclosureExclusions;
import com.zoop.graph.read.DisclosureExclusions.ArticleTarget;

/** Current source authority and durable source exclusions, shared by every version's read and publication gates. */
public final class GraphPublicationAuthority {
    private final DocumentRegistryRepository registry;
    private final DocumentReadSources sources;
    private final DisclosureExclusionReader exclusions;
    private final Clock clock;

    public GraphPublicationAuthority(DocumentRegistryRepository registry, DocumentReadSources sources,
            DisclosureExclusionReader exclusions, Clock clock) {
        this.registry = registry; this.sources = sources; this.exclusions = exclusions; this.clock = clock;
    }

    public DisclosureExclusions current(Publication publication, String requestId) {
        try {
            DisclosureExclusions own = exclusions.current(publication.versionId());
            Set<String> issues = new HashSet<>(own.issueIds()), relations = new HashSet<>(own.relationIds()), evidence = new HashSet<>(own.evidenceIds());
            Set<ArticleTarget> articles = new HashSet<>(own.articleTargets()); long revision = own.revision();
            SourceRegistry current = sources.registry(requestId);
            Instant at = clock.instant();
            for (var source : publication.contributions()) {
                DisclosureExclusions excluded = source.sourceVersionId().equals(publication.versionId()) ? own : exclusions.current(source.sourceVersionId());
                revision = Math.max(revision, excluded.revision());
                for (String issue : excluded.issueIds()) issues.add(publication.publicIssue(new IssueRef(source.sourceVersionId(), issue)));
                relations.addAll(excluded.relationIds()); evidence.addAll(excluded.evidenceIds()); articles.addAll(excluded.articleTargets());
                for (var article : source.projection().articles()) {
                    if (!allowed(source, article, registry, current, at)) articles.add(new ArticleTarget(article.articleId(), article.version()));
                }
            }
            // A selected field's owner is an atomic proof: incidental surviving mentions cannot replace its headline.
            for (var owners : publication.issueSources().values()) {
                for (IssueRef owner : Set.copyOf(owners.headlineSources().values())) {
                    var original = publication.originalIssue(owner);
                    var source = publication.source(owner.sourceVersionId());
                    boolean lost = original.evidenceIds().stream().anyMatch(evidence::contains)
                            || original.geographyEvidenceIds().stream().anyMatch(evidence::contains)
                            || source.projection().evidence().stream().anyMatch(e -> (original.evidenceIds().contains(e.evidenceId())
                                || original.geographyEvidenceIds().contains(e.evidenceId())) && articles.contains(new ArticleTarget(e.articleId(), e.articleVersion())))
                            || original.mentions().stream().anyMatch(m -> articles.contains(new ArticleTarget(m.articleId(), m.articleVersion())));
                    if (lost) { issues.add(owners.issueId()); break; }
                }
            }
            return new DisclosureExclusions(revision, issues, relations, evidence, articles);
        } catch (PublicationException | GraphReceiptGrants.Malformed | StrictJson.Malformed | SourceRegistry.Invalid malformed) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, false);
        }
    }

    /** Full retained closure rights; a denied hidden contribution cannot be copied into a new full-text publication. */
    public void requireFullRights(Publication publication, String requestId) {
        requireFullRights(publication.contributions(), requestId);
    }

    public void requireFullRights(Publication publication, String requestId, Instant at) {
        requireFullRights(publication, registry, sources.registry(requestId), at);
    }

    public static void requireFullRights(Publication publication, DocumentRegistryRepository registry, SourceRegistry current, Instant at) {
        requireFullRights(publication.contributions(), registry, current, at);
    }

    public void requireFullRights(java.util.List<GraphPublicationReader.Contribution> contributions, String requestId) {
        try {
            requireFullRights(contributions, registry, sources.registry(requestId), clock.instant());
        } catch (SourceRegistry.Invalid | GraphReceiptGrants.Malformed | StrictJson.Malformed malformed) {
            throw new PublicationException("source_authority_unavailable");
        } catch (CustomException unavailable) {
            throw new PublicationException("source_authority_unavailable");
        }
    }

    private static void requireFullRights(java.util.List<GraphPublicationReader.Contribution> contributions,
            DocumentRegistryRepository registry, SourceRegistry current, Instant at) {
        try {
            current.checkRoutingUnchanged();
            for (var source : contributions) for (var article : source.projection().articles()) {
                if (!allowed(source, article, registry, current, at))
                    throw new PublicationException("rights_denied");
            }
            current.checkRoutingUnchanged();
        } catch (SourceRegistry.Invalid | GraphReceiptGrants.Malformed | StrictJson.Malformed malformed) {
            throw new PublicationException("source_authority_unavailable");
        }
    }

    private static boolean allowed(GraphPublicationReader.Contribution source, com.zoop.graph.snapshot.PublicGraphSnapshot.Article projected,
            DocumentRegistryRepository registry, SourceRegistry current, Instant at) {
        String articleId = projected.articleId(), articleVersion = projected.version();
        var article = registry.findArticle(articleId).orElseThrow(() -> new PublicationException("basis_unavailable"));
        var version = registry.findVersion(articleId, articleVersion).orElseThrow(() -> new PublicationException("basis_unavailable"));
        var text = registry.findArtifact(version.textArtifactId()).orElseThrow(() -> new PublicationException("basis_unavailable"));
        var facts = source.bundle().objects("articles").stream().filter(a -> a.string("articleId").equals(articleId)
                && a.string("articleVersion").equals(articleVersion)).toList();
        if (facts.size() != 1 || !"extracted_text".equals(text.kind()) || !text.sha256().equals(facts.getFirst().string("textSha256")))
            throw new PublicationException("basis_mismatch");
        String published = switch (version.publicationPrecision()) {
            case "datetime" -> version.publishedAt() == null ? null : version.publishedAt().toString();
            case "day" -> version.publishedDate() == null ? null : version.publishedDate().toString();
            case "unknown" -> null;
            default -> throw new PublicationException("basis_mismatch");
        };
        if (!java.util.Objects.equals(projected.title(), version.title()) || !java.util.Objects.equals(projected.url(), version.url())
                || !java.util.Objects.equals(projected.publishedAt(), published)) throw new PublicationException("basis_mismatch");
        boolean allowed = "available".equals(article.accessStatus());
        for (var pin : GraphReceiptGrants.pins(source.bundle(), articleId, articleVersion)) {
            if (!pin.sourceId().equals(article.provider())) throw new PublicationException("basis_mismatch");
            String denial = pin.legacyArticleUrl() == null ? current.denial(pin.sourceId(), pin.grantId(), pin.revision(), at)
                    : current.denialForUrl(pin.sourceId(), pin.grantId(), pin.revision(), pin.legacyArticleUrl(), at);
            if (denial != null) allowed = false;
        }
        return allowed;
    }
}
