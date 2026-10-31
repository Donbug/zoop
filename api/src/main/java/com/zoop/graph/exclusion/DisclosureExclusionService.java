package com.zoop.graph.exclusion;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.function.Supplier;

import com.zoop.ai.AiClientException;
import com.zoop.ai.AiServiceRejectionException;
import com.zoop.ai.handoff.HandoffExposureClient;
import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.artifact.storage.ArtifactStoreException;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import com.zoop.common.json.StrictJson.Obj;
import com.zoop.document.repository.ArtifactRow;
import com.zoop.document.repository.DocumentRegistryRepository;
import com.zoop.graph.exclusion.ExclusionRequest.Exclude;
import com.zoop.graph.exclusion.ExclusionRequest.Handoff;
import com.zoop.graph.exclusion.ExclusionRequest.Lift;
import com.zoop.graph.exclusion.ExclusionRequest.Query;
import com.zoop.graph.exclusion.ExclusionRequest.Report;
import com.zoop.graph.exclusion.ExclusionRequest.Target;
import com.zoop.graph.exclusion.ExclusionResult.VersionChange;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DataAccessException;
import org.springframework.transaction.TransactionException;
import org.springframework.transaction.support.TransactionCallback;
import org.springframework.transaction.support.TransactionOperations;
import tools.jackson.databind.JsonNode;

/**
 * Writes the public exclusion store from operator input (FS081, api/docs/GRAPH_READ_HANDOFF.md "공개 영향 ID 인계"):
 * <ul>
 * <li>{@code exclude}: every handoff of an AI exposure report must be a graph version this app imported, and the receipt of that
 *     version must carry the report's handoff id and all three digests (rule 1). Its proposed ids are then excluded in THAT
 *     version only (rule 3). Targets already excluded are left as they are, so the same report twice changes nothing.</li>
 * <li>{@code exclude-query}: the same, with the report read from the AI service ({@code queryGraphHandoffExposure}) for the
 *     handoffs of the named versions (default: the active version and the imported ones after it). The report must answer
 *     exactly that change and those handoffs. A query failure writes nothing; a re-run of a recorded request asks nothing.</li>
 * <li>{@code lift}: the only way an exclusion ends. A report never lifts anything, however small or empty (rule 4). Refused when
 *     a target changed after the lift's {@code expectedRevision}: a lift never undoes a change its operator did not see.</li>
 * </ul>
 * Every command that ran to an outcome is recorded by its {@code requestId} in the transaction of its change. A re-run of the same
 * request (an empty result file, {@code outcome_unknown}) returns that stored result and changes nothing again; the same id with
 * another request is refused. A commit that may or may not have happened is {@code outcome_unknown}, never "nothing written".
 * A change is one transaction under the shared publication lock (rule switches, review decisions and activation take it too):
 * {@code revision} is MAX+1 and the lock is held to the commit, so readers see a committed prefix without the lock. The receipts are
 * read and checked before that transaction: they are immutable, verified files and the lock is held only for the short write.
 */
public final class DisclosureExclusionService {
    static final String RECEIPT_KIND = "verification_receipt";
    /** New exposure queries follow the producer's current contract; retained reports bind their own schema to the receipt. */
    static final String BUNDLE_SCHEMA = "zoop-graph-handoff-bundle-8";
    private static final Logger log = LoggerFactory.getLogger(DisclosureExclusionService.class);

    private final JdbcDisclosureExclusionRepository repository;
    private final DocumentRegistryRepository registry;
    private final ArtifactFileStore store;
    private final TransactionOperations transaction;
    private final HandoffExposureClient exposure;
    private final com.zoop.graph.publication.GraphPublicationReader publications;


    /** {@code exposure} null: an {@code exclude-query} is {@code exposure_unavailable}; report files still work. */
    public DisclosureExclusionService(JdbcDisclosureExclusionRepository repository, DocumentRegistryRepository registry,
            ArtifactFileStore store, TransactionOperations transaction, HandoffExposureClient exposure,
            com.zoop.graph.publication.GraphPublicationReader publications) {
        this.repository = repository;
        this.registry = registry;
        this.store = store;
        this.transaction = transaction;
        this.exposure = exposure;
        this.publications = publications;
    }

    /** The graph version an import staged from this handoff (the importer's id formula). */
    static String versionId(String handoffId) {
        return "gv-" + Canonical.sha256(handoffId);
    }

    public ExclusionResult run(ExclusionRequest request) {
        String action = request instanceof Lift ? "lift" : "exclude";
        try {
            ExclusionResult result = switch (request) {
                case Exclude exclude -> exclude(exclude);
                case Query query -> query(query);
                case Lift lift -> lift(lift);
                case ExclusionRequest.LegacyExclude legacy -> legacyExclude(legacy);
                case ExclusionRequest.PublicationExclude publication -> publicationExclude(publication);
            };
            log.info("disclosure exclusion {} {} at revision {}{}", action, result.outcome(), result.revision(),
                    result.replay() ? " (recorded result)" : "");
            return result;
        } catch (ExclusionException failure) {
            log.warn("disclosure exclusion {} failed: {}", action, failure.failure().code());
            return ExclusionResult.failed(action, failure);
        } catch (DataAccessException database) {
            // A read before the transaction: nothing was written.
            log.error("disclosure exclusion database failure: {}", database.getClass().getSimpleName());
            return ExclusionResult.failed(action, new ExclusionException(ExclusionFailure.DATABASE_UNAVAILABLE));
        } catch (com.zoop.graph.publication.PublicationException invalid) {
            return ExclusionResult.failed(action, new ExclusionException(ExclusionFailure.RECEIPT_UNAVAILABLE));
        }
    }

    private ExclusionResult exclude(Exclude request) {
        return exclude(request, Map.of());
    }

    /** {@code receipts}: the receipts already read and verified for some versions, so they are not read again. */
    private ExclusionResult exclude(Exclude request, Map<String, Obj> receipts) {
        Optional<ExclusionResult> recorded = recorded(request);
        if (recorded.isPresent()) return recorded.get();
        Map<String, Handoff> byVersion = new LinkedHashMap<>();
        for (Handoff handoff : request.report().handoffs()) {
            String versionId = versionId(handoff.handoffId());
            if (!"snapshot".equals(repository.versionKind(versionId).orElse(null))) {
                throw new ExclusionException(ExclusionFailure.VERSION_UNKNOWN);
            }
            verifyReceipt(handoff, receipts.containsKey(versionId) ? receipts.get(versionId) : receipt(versionId));
            byVersion.put(versionId, handoff);
        }
        return commit(request, () -> {
            List<VersionChange> versions = new ArrayList<>();
            Map<String, List<Target>> fresh = new LinkedHashMap<>();
            for (Map.Entry<String, Handoff> entry : byVersion.entrySet()) {
                Set<Target> current = repository.excluded(entry.getKey());
                List<Target> added = entry.getValue().targets().stream().filter(t -> !current.contains(t)).toList();
                List<Target> kept = entry.getValue().targets().stream().filter(current::contains).toList();
                fresh.put(entry.getKey(), added);
                versions.add(new VersionChange(entry.getKey(), entry.getValue().handoffId(), entry.getValue().exposed(),
                        byKind(added), byKind(kept)));
            }
            return write("exclude", request.report().cause(), request.report().sha256(), request, fresh, versions);
        });
    }

    private ExclusionResult legacyExclude(ExclusionRequest.LegacyExclude request) {
        Optional<ExclusionResult> recorded = recorded(request);
        if (recorded.isPresent()) return recorded.get();
        if (!"snapshot".equals(repository.versionKind(request.graphVersionId()).orElse(null)))
            throw new ExclusionException(ExclusionFailure.VERSION_UNKNOWN);
        ArtifactRow artifact = registry.findArtifact("artifact-receipt-" + request.graphVersionId())
                .orElseThrow(() -> new ExclusionException(ExclusionFailure.RECEIPT_UNAVAILABLE));
        if (!artifact.sha256().equals(request.receiptSha256())) throw new ExclusionException(ExclusionFailure.RECEIPT_MISMATCH);
        Obj receipt = receipt(request.graphVersionId());
        try {
            receipt.exactly(com.zoop.graph.importer.LegacyRealPackage.RECEIPT_KEYS);
            if (!com.zoop.graph.importer.LegacyRealPackage.isReceiptSchema(receipt.string("schemaVersion"))
                    || !request.graphVersionId().equals(versionId(receipt.string("migrationId"))))
                throw new StrictJson.Malformed();
            Obj bundle = receipt.object("bundle");
            for (Target target : request.targets()) {
                boolean member = switch (target.kind()) {
                    case "article" -> bundle.objects("articles").stream().anyMatch(a -> target.id().equals(a.string("articleId"))
                            && target.articleVersion().equals(a.string("articleVersion")));
                    case "issue" -> bundle.objects("issues").stream().anyMatch(i -> target.id().equals(i.string("id")));
                    case "relation" -> bundle.objects("relations").stream().anyMatch(r -> target.id().equals(r.string("id")));
                    case "evidence" -> bundle.objects("evidence").stream().anyMatch(e -> target.id().equals(e.string("id")));
                    default -> false;
                };
                if (!member) throw new StrictJson.Malformed();
            }
        } catch (StrictJson.Malformed invalid) {
            throw new ExclusionException(ExclusionFailure.RECEIPT_MISMATCH);
        }
        return commit(request, () -> {
            Set<Target> current = repository.excluded(request.graphVersionId());
            List<Target> added = request.targets().stream().filter(t -> !current.contains(t)).toList();
            List<Target> kept = request.targets().stream().filter(current::contains).toList();
            return write("exclude", "legacy-operator", request.receiptSha256(), request, Map.of(request.graphVersionId(), added),
                    List.of(new VersionChange(request.graphVersionId(), null, !request.targets().isEmpty(),
                            byKind(added), byKind(kept))));
        });
    }

    private ExclusionResult publicationExclude(ExclusionRequest.PublicationExclude request) {
        Optional<ExclusionResult> recorded = recorded(request);
        if (recorded.isPresent()) return recorded.get();
        var publication = publications.read(request.graphVersionId());
        if (!publication.composed() || !publication.receipt().sha256().equals(request.receiptSha256()))
            throw new ExclusionException(ExclusionFailure.RECEIPT_MISMATCH);
        Map<String, Set<Target>> owners = new java.util.TreeMap<>();
        for (Target target : request.targets()) {
            boolean resolved = false;
            for (var source : publication.contributions()) {
                List<Target> original = switch (target.kind()) {
                    case "issue" -> {
                        var issue = publication.issueSources().get(target.id());
                        yield issue == null ? List.of() : issue.members().stream()
                                .filter(r -> r.sourceVersionId().equals(source.sourceVersionId()))
                                .map(r -> new Target("issue", r.issueId(), "")).toList();
                    }
                    case "relation" -> {
                        var relation = publication.relationSources().get(target.id());
                        yield relation == null ? List.of() : relation.sources().stream()
                                .filter(r -> r.sourceVersionId().equals(source.sourceVersionId()))
                                .map(r -> new Target("relation", r.relationId(), "")).toList();
                    }
                    case "evidence" -> source.projection().evidence().stream().anyMatch(e -> e.evidenceId().equals(target.id())) ? List.of(target) : List.of();
                    case "article" -> source.projection().articles().stream().anyMatch(a -> a.articleId().equals(target.id())
                            && a.version().equals(target.articleVersion())) ? List.of(target) : List.of();
                    default -> throw new ExclusionException(ExclusionFailure.REQUEST_INVALID);
                };
                if (!original.isEmpty()) {
                    resolved = true;
                    owners.computeIfAbsent(source.sourceVersionId(), ignored -> new java.util.LinkedHashSet<>()).addAll(original);
                }
            }
            if (!resolved) throw new ExclusionException(ExclusionFailure.RECEIPT_MISMATCH);
        }
        return commit(request, () -> {
            List<VersionChange> changes = new ArrayList<>(); Map<String, List<Target>> fresh = new LinkedHashMap<>();
            for (var entry : owners.entrySet()) {
                Set<Target> current = repository.excluded(entry.getKey());
                List<Target> added = entry.getValue().stream().filter(t -> !current.contains(t)).toList();
                List<Target> kept = entry.getValue().stream().filter(current::contains).toList();
                fresh.put(entry.getKey(), added);
                changes.add(new VersionChange(entry.getKey(), publication.source(entry.getKey()).sourceId(), true, byKind(added), byKind(kept)));
            }
            return write("exclude", "publication-operator", request.receiptSha256(), request, fresh, changes);
        });
    }

    private ExclusionResult query(Query request) {
        boolean byDefault = request.graphVersionIds().isEmpty();
        Map<String, Obj> receipts = new LinkedHashMap<>();
        for (String versionId : byDefault ? repository.exposureTargets() : request.graphVersionIds()) {
            if (!"snapshot".equals(repository.versionKind(versionId).orElse(null)))
                throw new ExclusionException(ExclusionFailure.VERSION_UNKNOWN);
            Obj selected = receipt(versionId);
            if (com.zoop.graph.publication.GraphPublicationReader.RECEIPT_SCHEMA.equals(selected.string("schemaVersion"))) {
                var publication = publications.read(versionId);
                for (var source : publication.contributions()) {
                    if (!"native".equals(source.sourceKind())) throw new ExclusionException(ExclusionFailure.VERSIONS_INVALID);
                    Obj original = receipt(source.sourceVersionId());
                    if (!BUNDLE_SCHEMA.equals(bundleSchema(original)) && !"zoop-graph-handoff-bundle-9".equals(bundleSchema(original)))
                        throw new ExclusionException(ExclusionFailure.VERSIONS_INVALID);
                    receipts.put(source.sourceVersionId(), original);
                }
            } else {
                if (!BUNDLE_SCHEMA.equals(bundleSchema(selected)) && !"zoop-graph-handoff-bundle-9".equals(bundleSchema(selected)))
                    throw new ExclusionException(ExclusionFailure.VERSIONS_INVALID);
                receipts.put(versionId, selected);
            }
            if (receipts.size() > HandoffExposureClient.MAX_HANDOFFS)
                throw new ExclusionException(ExclusionFailure.EXPOSURE_BATCH_REQUIRED);
        }
        if (receipts.isEmpty()) {
            throw new ExclusionException(ExclusionFailure.VERSIONS_INVALID);
        }
        List<String> handoffIds = new ArrayList<>();
        for (Map.Entry<String, Obj> entry : receipts.entrySet()) {
            String handoffId;
            try {
                handoffId = entry.getValue().string("handoffId");
            } catch (StrictJson.Malformed missing) {
                throw new ExclusionException(ExclusionFailure.RECEIPT_MISMATCH);
            }
            if (!ExclusionRequestParser.ID.matcher(handoffId).matches() || !entry.getKey().equals(versionId(handoffId))) {
                throw new ExclusionException(ExclusionFailure.RECEIPT_MISMATCH);
            }
            handoffIds.add(handoffId);
        }
        // The versions resolved now are part of the command: the same file re-run over another set of versions (a version imported
        // meanwhile) is another request, refused as request_conflict once the first one is recorded.
        Query bound = new Query(request.requestId(),
                Canonical.sha256(request.requestSha256() + "\n" + String.join("\n", receipts.keySet())), request.operator(),
                request.reason(), request.changed(), request.cause(), List.copyOf(receipts.keySet()));
        Optional<ExclusionResult> recorded = recorded(bound);
        if (recorded.isPresent()) return recorded.get();
        if (exposure == null) throw new ExclusionException(ExclusionFailure.EXPOSURE_UNAVAILABLE);
        JsonNode answer;
        try {
            answer = exposure.exposure(handoffIds, request.changed());
        } catch (AiServiceRejectionException refused) {
            log.warn("disclosure exclusion exposure refused: {} {}", refused.httpStatus(), refused.code());
            // A 5xx envelope (runtime_busy, runtime_unavailable, service_configuration_invalid) is the service, not a refusal.
            throw new ExclusionException(refused.httpStatus() >= 500 ? ExclusionFailure.EXPOSURE_UNAVAILABLE
                    : ExclusionFailure.EXPOSURE_REFUSED);
        } catch (AiClientException unavailable) {
            log.warn("disclosure exclusion exposure unavailable: {}", unavailable.getClass().getSimpleName());
            throw new ExclusionException(ExclusionFailure.EXPOSURE_UNAVAILABLE);
        } catch (IllegalArgumentException outsideContract) {
            // The ids were checked above, so only the change can be outside the query contract.
            throw new ExclusionException(ExclusionFailure.REQUEST_INVALID);
        }
        Report report = ExclusionRequestParser.report(answer);
        // The answer is about exactly what was asked: this change (and so its cause) and these handoffs, which the producer
        // returns sorted by id (zoop-handoff-exposure-1 scope.handoffIds and handoffs), whatever order they were asked in.
        if (!report.handoffs().stream().map(Handoff::handoffId).toList().equals(handoffIds.stream().sorted().toList())
                || !Canonical.digest(answer.get("changed")).equals(Canonical.digest(request.changed()))) {
            throw new ExclusionException(ExclusionFailure.REPORT_INVALID);
        }
        return exclude(new Exclude(bound.requestId(), bound.requestSha256(), request.operator(), request.reason(), report), receipts);
    }

    /** The bundle schema a stored import receipt retains ({@code bundle.schemaVersion}); null when it does not say. */
    private static String bundleSchema(Obj receipt) {
        try {
            return receipt.object("bundle").string("schemaVersion");
        } catch (StrictJson.Malformed missing) {
            return null;
        }
    }

    private ExclusionResult lift(Lift request) {
        Optional<ExclusionResult> recorded = recorded(request);
        if (recorded.isPresent()) return recorded.get();
        if (repository.versionKind(request.graphVersionId()).isEmpty()) {
            throw new ExclusionException(ExclusionFailure.VERSION_UNKNOWN);
        }
        if ("snapshot".equals(repository.versionKind(request.graphVersionId()).orElse(null))
                && com.zoop.graph.publication.GraphPublicationReader.RECEIPT_SCHEMA.equals(receipt(request.graphVersionId()).string("schemaVersion")))
            throw new ExclusionException(ExclusionFailure.VERSIONS_INVALID);
        return commit(request, () -> {
            if (request.expectedRevision() > repository.revision()) throw new ExclusionException(ExclusionFailure.REVISION_STALE);
            Map<Target, Long> lastChanged = repository.lastChanged(request.graphVersionId());
            if (request.targets().stream().anyMatch(t -> lastChanged.getOrDefault(t, 0L) > request.expectedRevision())) {
                throw new ExclusionException(ExclusionFailure.REVISION_STALE);
            }
            Set<Target> current = repository.excluded(request.graphVersionId());
            List<Target> lifted = request.targets().stream().filter(current::contains).toList();
            List<Target> notExcluded = request.targets().stream().filter(t -> !current.contains(t)).toList();
            List<VersionChange> versions = List.of(new VersionChange(request.graphVersionId(), null, true, byKind(lifted),
                    byKind(notExcluded)));
            return write("lift", "operator", null, request, Map.of(request.graphVersionId(), lifted), versions);
        });
    }

    /** The stored result of this request id, if it already ran; the same id with another request is refused. */
    private Optional<ExclusionResult> recorded(ExclusionRequest request) {
        return repository.recorded(request.requestId()).map(found -> {
            if (!found.requestSha256().equals(request.requestSha256())) {
                throw new ExclusionException(ExclusionFailure.REQUEST_CONFLICT);
            }
            return ExclusionResult.replayed(request instanceof Lift ? "lift" : "exclude", found.result());
        });
    }

    /**
     * Runs {@code work} under the publication lock and records its result by request id in the same transaction. A statement that
     * fails inside is a known rollback; a failure of the transaction itself (the commit) leaves the outcome unknown.
     */
    private ExclusionResult commit(ExclusionRequest request, Supplier<ExclusionResult> work) {
        TransactionCallback<ExclusionResult> callback = status -> {
            try {
                repository.lockPublication();
                // Checked again under the lock: a concurrent run of the same request may have recorded it meanwhile.
                Optional<ExclusionResult> recorded = recorded(request);
                if (recorded.isPresent()) return recorded.get();
                ExclusionResult result = work.get();
                repository.insertRequest(request.requestId(), request.requestSha256(), result.action(), result.revision(),
                        ExclusionResultWriter.toBytes(result));
                return result;
            } catch (DataAccessException failure) {
                log.error("disclosure exclusion database failure: {}", failure.getClass().getSimpleName());
                throw new ExclusionException(ExclusionFailure.DATABASE_UNAVAILABLE);
            }
        };
        try {
            return transaction.execute(callback);
        } catch (DataAccessException | TransactionException unknownOutcome) {
            log.error("disclosure exclusion commit failure: {}", unknownOutcome.getClass().getSimpleName());
            throw new ExclusionException(ExclusionFailure.OUTCOME_UNKNOWN);
        }
    }

    /** One change with every target that moves, or nothing at all when none does. Runs under the publication lock. */
    private ExclusionResult write(String action, String cause, String reportSha256, ExclusionRequest request,
            Map<String, List<Target>> targets, List<VersionChange> versions) {
        if (targets.values().stream().allMatch(List::isEmpty)) {
            return new ExclusionResult(action, ExclusionResult.UNCHANGED, repository.revision(), versions);
        }
        long revision = repository.revision() + 1;
        repository.insertChange(revision, action, cause, reportSha256, request.reason(), request.operator());
        targets.forEach((versionId, list) -> list.forEach(target -> repository.insertTarget(revision, versionId, target)));
        return new ExclusionResult(action, ExclusionResult.APPLIED, revision, versions);
    }

    /** Rule 1: the report's handoff id and its three digests are exactly what the app's import receipt of the version holds. */
    private static void verifyReceipt(Handoff handoff, Obj receipt) {
        try {
            if (!handoff.handoffId().equals(receipt.string("handoffId"))
                    || !handoff.bundleSchema().equals(receipt.object("bundle").string("schemaVersion"))
                    || !handoff.manifestDigest().equals(receipt.string("manifestDigest"))
                    || !handoff.bundleDigest().equals(receipt.string("bundleDigest"))
                    || !handoff.contentDigest().equals(receipt.string("contentDigest"))) {
                throw new ExclusionException(ExclusionFailure.RECEIPT_MISMATCH);
            }
        } catch (StrictJson.Malformed missing) {
            throw new ExclusionException(ExclusionFailure.RECEIPT_MISMATCH);
        }
    }

    /** The registered, verified import receipt of the version. */
    private Obj receipt(String versionId) {
        ArtifactRow artifact = registry.findArtifact("artifact-receipt-" + versionId)
                .filter(row -> RECEIPT_KIND.equals(row.kind()))
                .orElseThrow(() -> new ExclusionException(ExclusionFailure.RECEIPT_UNAVAILABLE));
        Obj receipt;
        try {
            if (store == null) throw new ArtifactStoreException(ArtifactStoreException.Reason.UNAVAILABLE, "root_unset");
            receipt = StrictJson.parseObject(store.readVerified(artifact.storageUri(), artifact.sha256(), artifact.bytes()));
        } catch (ArtifactStoreException | StrictJson.Malformed unreadable) {
            throw new ExclusionException(ExclusionFailure.RECEIPT_UNAVAILABLE);
        }
        return receipt;
    }

    private static Map<String, Integer> byKind(List<Target> targets) {
        Map<String, Integer> counts = new LinkedHashMap<>();
        for (Target target : targets) {
            counts.merge(target.kind(), 1, Integer::sum);
        }
        return counts;
    }
}
