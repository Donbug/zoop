package com.zoop.graph.exclusion;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

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
import com.zoop.graph.exclusion.ExclusionRequest.Target;
import com.zoop.graph.exclusion.ExclusionResult.VersionChange;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DataAccessException;
import org.springframework.transaction.TransactionException;
import org.springframework.transaction.support.TransactionOperations;

/**
 * Writes the public exclusion store from operator input (FS081, api/docs/GRAPH_READ_HANDOFF.md "공개 영향 ID 인계"):
 * <ul>
 * <li>{@code exclude}: every handoff of an AI exposure report must be a graph version this app imported, and the receipt of that
 *     version must carry the report's handoff id and all three digests (rule 1). Its proposed ids are then excluded in THAT
 *     version only (rule 3). Targets already excluded are left as they are, so the same report twice changes nothing.</li>
 * <li>{@code lift}: the only way an exclusion ends. A report never lifts anything, however small or empty (rule 4).</li>
 * </ul>
 * A change is one transaction under the shared publication lock (rule switches, review decisions and activation take it too):
 * {@code revision} is MAX+1 and the lock is held to the commit, so readers see a committed prefix without the lock. The receipts are
 * read and checked before that transaction: they are immutable, verified files and the lock is held only for the short write.
 */
public final class DisclosureExclusionService {
    static final String RECEIPT_KIND = "verification_receipt";
    private static final Logger log = LoggerFactory.getLogger(DisclosureExclusionService.class);

    private final JdbcDisclosureExclusionRepository repository;
    private final DocumentRegistryRepository registry;
    private final ArtifactFileStore store;
    private final TransactionOperations transaction;

    public DisclosureExclusionService(JdbcDisclosureExclusionRepository repository, DocumentRegistryRepository registry,
            ArtifactFileStore store, TransactionOperations transaction) {
        this.repository = repository;
        this.registry = registry;
        this.store = store;
        this.transaction = transaction;
    }

    /** The graph version an import staged from this handoff (the importer's id formula). */
    static String versionId(String handoffId) {
        return "gv-" + Canonical.sha256(handoffId);
    }

    public ExclusionResult run(ExclusionRequest request) {
        String action = request instanceof Lift ? "lift" : "exclude";
        try {
            ExclusionResult result = request instanceof Exclude exclude ? exclude(exclude) : lift((Lift) request);
            log.info("disclosure exclusion {} {} at revision {}", action, result.outcome(), result.revision());
            return result;
        } catch (ExclusionException failure) {
            log.warn("disclosure exclusion {} failed: {}", action, failure.failure().code());
            return ExclusionResult.failed(action, failure);
        } catch (DataAccessException | TransactionException database) {
            log.error("disclosure exclusion database failure: {}", database.getClass().getSimpleName());
            return ExclusionResult.failed(action, new ExclusionException(ExclusionFailure.DATABASE_UNAVAILABLE));
        }
    }

    private ExclusionResult exclude(Exclude request) {
        Map<String, Handoff> byVersion = new LinkedHashMap<>();
        for (Handoff handoff : request.report().handoffs()) {
            String versionId = versionId(handoff.handoffId());
            if (!"snapshot".equals(repository.versionKind(versionId).orElse(null))) {
                throw new ExclusionException(ExclusionFailure.VERSION_UNKNOWN);
            }
            verifyReceipt(versionId, handoff);
            byVersion.put(versionId, handoff);
        }
        return transaction.execute(status -> {
            repository.lockPublication();
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

    private ExclusionResult lift(Lift request) {
        if (repository.versionKind(request.graphVersionId()).isEmpty()) {
            throw new ExclusionException(ExclusionFailure.VERSION_UNKNOWN);
        }
        return transaction.execute(status -> {
            repository.lockPublication();
            Set<Target> current = repository.excluded(request.graphVersionId());
            List<Target> lifted = request.targets().stream().filter(current::contains).toList();
            List<Target> notExcluded = request.targets().stream().filter(t -> !current.contains(t)).toList();
            List<VersionChange> versions = List.of(new VersionChange(request.graphVersionId(), null, true, byKind(lifted),
                    byKind(notExcluded)));
            return write("lift", "operator", null, request, Map.of(request.graphVersionId(), lifted), versions);
        });
    }

    /** One change with every target that moves, or nothing at all when none does. Runs under the publication lock. */
    private ExclusionResult write(String action, String cause, String reportSha256, ExclusionRequest request,
            Map<String, List<Target>> targets, List<VersionChange> versions) {
        if (targets.values().stream().allMatch(List::isEmpty)) {
            return new ExclusionResult(action, ExclusionResult.UNCHANGED, repository.revision(), versions, null);
        }
        long revision = repository.revision() + 1;
        repository.insertChange(revision, action, cause, reportSha256, request.reason(), request.operator());
        targets.forEach((versionId, list) -> list.forEach(target -> repository.insertTarget(revision, versionId, target)));
        return new ExclusionResult(action, ExclusionResult.APPLIED, revision, versions, null);
    }

    /** Rule 1: the report's handoff id and its three digests are exactly what the app's import receipt of the version holds. */
    private void verifyReceipt(String versionId, Handoff handoff) {
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
        try {
            if (!handoff.handoffId().equals(receipt.string("handoffId"))
                    || !handoff.manifestDigest().equals(receipt.string("manifestDigest"))
                    || !handoff.bundleDigest().equals(receipt.string("bundleDigest"))
                    || !handoff.contentDigest().equals(receipt.string("contentDigest"))) {
                throw new ExclusionException(ExclusionFailure.RECEIPT_MISMATCH);
            }
        } catch (StrictJson.Malformed missing) {
            throw new ExclusionException(ExclusionFailure.RECEIPT_MISMATCH);
        }
    }

    private static Map<String, Integer> byKind(List<Target> targets) {
        Map<String, Integer> counts = new LinkedHashMap<>();
        for (Target target : targets) {
            counts.merge(target.kind(), 1, Integer::sum);
        }
        return counts;
    }
}
