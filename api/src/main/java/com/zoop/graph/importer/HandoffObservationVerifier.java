package com.zoop.graph.importer;

import java.time.Instant;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import com.zoop.document.DocumentImportException;
import com.zoop.document.importer.IngestionExportParser;
import com.zoop.document.importer.IngestionExporter;
import com.zoop.document.importer.Observation;
import com.zoop.document.importer.VerifiedDocument;
import com.zoop.graph.importer.HandoffBundle.Article;
import com.zoop.graph.importer.HandoffBundle.Evidence;
import com.zoop.graph.importer.HandoffBundle.ObservationPin;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ArrayNode;

/**
 * The rights and source check of EVERY observation the bundle records, through the S2-1 export with {@code --require-store}:
 * the installed {@code zoop-ai-ingest} as one fresh subprocess per observation, or ai/service's observation export route
 * (one request per observation); nothing is cached in either case. The bundle's own grant
 * fields are data, not authority: the app persists quotes of these documents, so it needs the CURRENT registry to allow
 * {@code read}, {@code store} and {@code quote-display}, which the handoff CLI does not check ({@code store}) and which may have
 * changed since the freeze.
 *
 * <p>An export must be exactly the observation the bundle names (the existing strict S2-1 parser decides), under the same grant
 * id and revision, with the same observation time, and must state the article's title, URL and publication time as the bundle
 * does. Every observation of one article carries the same text and the same raw locators. For each evidence span the
 * producer's {@code sourceEvidenceId} and {@code rawLocatorIds} are recomputed from the current export. Only hashes and sizes
 * of the text are kept; the text itself is read again from the app's own artifact, which must equal it.
 */
final class HandoffObservationVerifier {
    /** One locator run of the exported document: a raw locator id and the code point interval it covers. */
    record Locator(String id, int start, int end) {
    }

    /**
     * What one current export proved. Two runs of the same check must produce equal facts; any difference means the rights or
     * the source moved in between.
     */
    record ObservationFacts(String articleId, String articleVersion, Observation selector, String grantId,
            String grantRevision, Instant observedAt, String textArtifactId, String textSha256, long textBytes,
            List<Locator> locators) {
        ObservationFacts {
            locators = List.copyOf(locators);
        }
    }

    private final IngestionExporter exporter;
    private final IngestionExportParser parser;

    HandoffObservationVerifier(IngestionExporter exporter, IngestionExportParser parser) {
        this.exporter = exporter;
        this.parser = parser;
    }

    /** Every observation in bundle order (articles, then their observations); the first failure stops the run. */
    List<ObservationFacts> collect(HandoffBundle bundle) {
        List<ObservationFacts> facts = new ArrayList<>();
        Map<String, ObservationFacts> firstByArticle = new HashMap<>();
        int index = 0;
        for (Article article : bundle.articles()) {
            for (ObservationPin pin : article.observations()) {
                Observation selector = new Observation(pin.roundId(), pin.sourceId(), pin.page(), pin.ordinal(),
                        article.documentId(), article.rawVersion(), article.documentVersion());
                VerifiedDocument document;
                try {
                    document = parser.parse(exporter.export(selector), selector);
                } catch (DocumentImportException failure) {
                    throw translate(failure, index);
                }
                ObservationFacts fact = check(article, pin, document, index);
                String key = article.articleId() + "\n" + article.articleVersion();
                ObservationFacts first = firstByArticle.putIfAbsent(key, fact);
                if (first != null && !sameText(first, fact)) {
                    throw new GraphHandoffException(GraphHandoffFailure.TEXT_MISMATCH).atObservation(index);
                }
                facts.add(fact);
                index++;
            }
        }
        return facts;
    }

    /**
     * The facts of one article (its first observation), keyed by {@code articleId + "\n" + articleVersion}, after the evidence
     * of the bundle was checked against them: the S2-1 evidence id and the raw locators recomputed from the export.
     */
    static Map<String, ObservationFacts> byArticle(HandoffBundle bundle, List<ObservationFacts> facts) {
        Map<String, ObservationFacts> byArticle = new HashMap<>();
        for (ObservationFacts fact : facts) {
            byArticle.putIfAbsent(fact.articleId() + "\n" + fact.articleVersion(), fact);
        }
        for (Evidence evidence : bundle.evidence()) {
            ObservationFacts fact = byArticle.get(evidence.articleId() + "\n" + evidence.articleVersion());
            if (fact == null || !evidence.textArtifactId().equals(fact.textArtifactId())) {
                throw new GraphHandoffException(GraphHandoffFailure.EVIDENCE_INVALID);
            }
            ArrayNode preimage = StrictJson.newArray();
            preimage.add(evidence.documentVersion());
            preimage.add(evidence.start());
            preimage.add(evidence.end());
            String sourceEvidenceId = "ev-" + Canonical.digest(preimage).substring(0, 32);
            List<String> locators = new ArrayList<>();
            for (Locator locator : fact.locators()) {
                if (locator.start() <= evidence.start() && evidence.start() < evidence.end() && evidence.end() <= locator.end()) {
                    locators.add(locator.id());
                }
            }
            locators.sort(HandoffBundleVerifier::compareCodePoints);
            // The table needs at least one locator, and the producer's list is exactly the runs that contain the span.
            if (!sourceEvidenceId.equals(evidence.sourceEvidenceId()) || locators.isEmpty()
                    || !locators.equals(evidence.rawLocatorIds())) {
                throw new GraphHandoffException(GraphHandoffFailure.EVIDENCE_INVALID);
            }
        }
        return byArticle;
    }

    private static ObservationFacts check(Article article, ObservationPin pin, VerifiedDocument document, int index) {
        if (!pin.grantId().equals(document.grantId()) || !pin.grantRevision().equals(document.grantRevision())
                || !HandoffTime.instant(pin.observedAt()).equals(document.observedAt())
                || !article.title().equals(document.title()) || !article.url().equals(document.url())
                || !samePublication(article, document)) {
            throw new GraphHandoffException(GraphHandoffFailure.OBSERVATION_MISMATCH).atObservation(index);
        }
        return new ObservationFacts(article.articleId(), article.articleVersion(), document.observation(),
                document.grantId(), document.grantRevision(), document.observedAt(), document.textArtifactId(),
                Canonical.sha256(document.textUtf8()), document.textUtf8().length, locators(document, index));
    }

    private static boolean samePublication(Article article, VerifiedDocument document) {
        return switch (article.precision()) {
            case "datetime" -> "datetime".equals(document.publicationPrecision()) && document.publishedAt() != null
                    && document.publishedAt().equals(HandoffTime.instant(article.publishedAt()));
            case "day" -> "day".equals(document.publicationPrecision()) && document.publishedDate() != null
                    && document.publishedDate().toString().equals(article.publishedAt());
            default -> "unknown".equals(document.publicationPrecision()) && document.publishedAt() == null
                    && document.publishedDate() == null;
        };
    }

    private static List<Locator> locators(VerifiedDocument document, int index) {
        try {
            List<Locator> locators = new ArrayList<>();
            for (StrictJson.Obj run : StrictJson.Obj.of(document.document()).objects("rawLocators")) {
                run.requiring(Set.of("locatorId", "start", "end"));
                locators.add(new Locator(run.string("locatorId"), run.count("start"), run.count("end")));
            }
            return locators;
        } catch (StrictJson.Malformed malformed) {
            throw new GraphHandoffException(GraphHandoffFailure.INGESTION_EXPORT_INVALID).atObservation(index);
        }
    }

    private static boolean sameText(ObservationFacts first, ObservationFacts other) {
        return first.textArtifactId().equals(other.textArtifactId()) && first.textSha256().equals(other.textSha256())
                && first.textBytes() == other.textBytes() && first.locators().equals(other.locators());
    }

    private static GraphHandoffException translate(DocumentImportException failure, int index) {
        return switch (failure.failure()) {
            case INGESTION_EXPORT_FAILED -> GraphHandoffException.ingestion(GraphHandoffFailure.INGESTION_EXPORT_FAILED,
                    failure.ingestionCode(), index);
            case INGESTION_EXPORT_UNAVAILABLE -> GraphHandoffException.ingestion(
                    GraphHandoffFailure.INGESTION_EXPORT_UNAVAILABLE, null, index);
            default -> GraphHandoffException.ingestion(GraphHandoffFailure.INGESTION_EXPORT_INVALID, null, index);
        };
    }
}
