package com.zoop.graph.publication;

import java.time.Clock;
import java.time.Instant;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import com.zoop.document.evidence.service.DocumentReadSources;
import com.zoop.document.evidence.service.GraphReceiptGrants;
import com.zoop.document.importer.SourceRegistry;
import com.zoop.document.repository.DocumentRegistryRepository;
import com.zoop.document.repository.DocumentRegistryRepository.ArticleFacts;
import com.zoop.document.repository.DocumentRegistryRepository.ArticleVersion;
import com.zoop.graph.publication.GraphPublicationReader.IssueRef;
import com.zoop.graph.publication.GraphPublicationReader.Publication;
import com.zoop.graph.read.DisclosureExclusionReader;
import com.zoop.graph.read.DisclosureExclusions;
import com.zoop.graph.read.DisclosureExclusions.ArticleTarget;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;

/** Current source authority and durable source exclusions, shared by every version's read and publication gates. */
public final class GraphPublicationAuthority {
    private static final Logger log = LoggerFactory.getLogger(GraphPublicationAuthority.class);
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
            // A version that is its own source maps its issue exclusions in the loop below, like every source.
            boolean ownIsSource = publication.contributions().stream().anyMatch(c -> c.sourceVersionId().equals(publication.versionId()));
            Set<String> issues = new HashSet<>(ownIsSource ? Set.of() : own.issueIds()), relations = new HashSet<>(own.relationIds()), evidence = new HashSet<>(own.evidenceIds());
            Set<ArticleTarget> articles = new HashSet<>(own.articleTargets()); long revision = own.revision();
            SourceRegistry current = sources.registry(requestId);
            Instant at = clock.instant();
            var facts = articleFacts(publication.contributions(), registry);
            var effective = publication.effective();
            for (var source : publication.contributions()) {
                DisclosureExclusions excluded = source.sourceVersionId().equals(publication.versionId()) ? own : exclusions.current(source.sourceVersionId());
                revision = Math.max(revision, excluded.revision());
                // An id the source does not hold filters nothing: an activation carries an exclusion to a new source whether or
                // not it holds the id (#55 A-14), and the record stays for a later source that does.
                Set<String> held = new HashSet<>();
                for (var issue : source.projection().issues()) held.add(issue.issueId());
                for (String issue : excluded.issueIds()) {
                    if (!held.contains(issue)) continue;
                    IssueRef original = new IssueRef(source.sourceVersionId(), issue);
                    // An original a decision in force removed (an excluded member, a retired issue's member) is not public, so its
                    // exclusion hides nothing now; any other original the receipt does not place is a damaged basis, as before.
                    var publicId = publication.findPublicIssue(original);
                    if (publicId.isPresent()) issues.add(publicId.get());
                    else if (!effective.voided(original)) throw new PublicationException("basis_mismatch");
                }
                relations.addAll(excluded.relationIds()); evidence.addAll(excluded.evidenceIds()); articles.addAll(excluded.articleTargets());
                for (var article : source.projection().articles()) {
                    if (!allowed(source, article, facts, current, at)) articles.add(new ArticleTarget(article.articleId(), article.version()));
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
            String category;
            String reason;
            if (malformed instanceof PublicationException failure) {
                category = "publication";
                // PublicationException accepts arbitrary strings; only these local basis codes are safe to emit.
                reason = switch (failure.code()) {
                    case "basis_unavailable" -> "basis_unavailable";
                    case "basis_mismatch" -> "basis_mismatch";
                    case null, default -> "publication_invalid";
                };
            } else if (malformed instanceof GraphReceiptGrants.Malformed) {
                category = "receipt"; reason = "receipt_invalid";
            } else if (malformed instanceof StrictJson.Malformed) {
                category = "json"; reason = "json_invalid";
            } else {
                category = "registry";
                reason = switch (((SourceRegistry.Invalid) malformed).code()) {
                    case "source_registry_unreadable" -> "source_registry_unreadable";
                    case "source_registry_too_large" -> "source_registry_too_large";
                    case null, default -> "source_registry_invalid";
                };
            }
            String correlation = requestId == null ? MDC.get("requestId") : requestId;
            String fingerprint = correlation == null ? "unavailable" : Canonical.sha256(correlation);
            if (malformed instanceof SourceRegistry.Invalid failure) {
                log.warn("Graph publication authority unavailable (category={}, reason={}, requestFingerprint={}, failureKind={}, interrupted={})",
                        category, reason, fingerprint, failure.failureKind(), failure.interrupted());
            } else {
                log.warn("Graph publication authority unavailable (category={}, reason={}, requestFingerprint={})",
                        category, reason, fingerprint);
            }
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

    public void requireFullRights(List<GraphPublicationReader.Contribution> contributions, String requestId) {
        try {
            requireFullRights(contributions, registry, sources.registry(requestId), clock.instant());
        } catch (SourceRegistry.Invalid | GraphReceiptGrants.Malformed | StrictJson.Malformed malformed) {
            throw new PublicationException("source_authority_unavailable");
        } catch (CustomException unavailable) {
            throw new PublicationException("source_authority_unavailable");
        }
    }

    private static void requireFullRights(List<GraphPublicationReader.Contribution> contributions,
            DocumentRegistryRepository registry, SourceRegistry current, Instant at) {
        try {
            current.checkRoutingUnchanged();
            var facts = articleFacts(contributions, registry);
            for (var source : contributions) for (var article : source.projection().articles()) {
                if (!allowed(source, article, facts, current, at))
                    throw new PublicationException("rights_denied");
            }
            current.checkRoutingUnchanged();
        } catch (SourceRegistry.Invalid | GraphReceiptGrants.Malformed | StrictJson.Malformed malformed) {
            throw new PublicationException("source_authority_unavailable");
        }
    }

    private static Map<ArticleVersion, ArticleFacts> articleFacts(List<GraphPublicationReader.Contribution> contributions,
            DocumentRegistryRepository registry) {
        Set<ArticleVersion> identities = new HashSet<>();
        for (var source : contributions) for (var article : source.projection().articles())
            identities.add(new ArticleVersion(article.articleId(), article.version()));
        return registry.findArticleFacts(identities);
    }

    private static boolean allowed(GraphPublicationReader.Contribution source, com.zoop.graph.snapshot.PublicGraphSnapshot.Article projected,
            Map<ArticleVersion, ArticleFacts> registryFacts, SourceRegistry current, Instant at) {
        String articleId = projected.articleId(), articleVersion = projected.version();
        var registered = registryFacts.get(new ArticleVersion(articleId, articleVersion));
        if (registered == null) throw new PublicationException("basis_unavailable");
        var article = registered.article(); var version = registered.version(); var text = registered.text();
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
