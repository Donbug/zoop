package com.zoop.graph.exclusion;

import java.util.List;
import java.util.Set;

import com.zoop.graph.exclusion.ExclusionRequest.Target;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Carries the public version's unlifted exclusions to the version an activation makes public (#55 A-14, FS081). Exclusions are
 * per version, so without this an exclusion applied to the public version would end with the next round's activation. Runs inside
 * the activation transaction, under the publication lock the activation holds, before the activation reads the new version's
 * overlay: the carried targets are then part of the pre-activation checks, and a refused activation rolls them back with it.
 * <p>
 * Every target currently excluded in {@code baseVersionId} (the version public until now) and not yet excluded in
 * {@code targetVersionId} is appended as one {@code exclude} change with cause {@code carried}, whether or not the new snapshot
 * holds the id: a lift is the only end of an exclusion (exposure consumption rule 4), and an id absent from the snapshot filters
 * nothing. A target the operator lifted on the new version itself (its latest change there is a lift: a corrected content seen
 * and released while the version waited) is not carried over that decision. Nothing is written when there is nothing to carry,
 * so a re-activation or a retried activation appends nothing twice. A lift on the public version is not carried either: that is
 * how a lift propagates to the versions activated after it.
 */
public class DisclosureExclusionCarry {
    public static final String CAUSE = "carried";
    private static final Logger log = LoggerFactory.getLogger(DisclosureExclusionCarry.class);

    private final JdbcDisclosureExclusionRepository repository;

    public DisclosureExclusionCarry(JdbcDisclosureExclusionRepository repository) {
        this.repository = repository;
    }

    /**
     * Appends the carried change for {@code targetVersionId} and returns how many targets it carried (0: nothing written).
     * {@code activatedBy} names the activation's actor for the change's reason ({@code system} or {@code admin:<id>}); the
     * change's operator is always {@code system}. Must run under the publication lock, in the activation's transaction.
     */
    public int carry(String baseVersionId, String targetVersionId, String activatedBy) {
        if (baseVersionId == null || baseVersionId.equals(targetVersionId)) return 0;
        Set<Target> base = repository.excluded(baseVersionId);
        if (base.isEmpty()) return 0;
        Set<Target> already = repository.excluded(targetVersionId);
        Set<Target> lifted = repository.lifted(targetVersionId);
        List<Target> carried = base.stream().filter(target -> !already.contains(target) && !lifted.contains(target)).toList();
        if (carried.isEmpty()) return 0;
        long revision = repository.revision() + 1;
        repository.insertChange(revision, "exclude", CAUSE, null, baseVersionId,
                "carried from " + baseVersionId + " at activation by " + activatedBy, "system");
        repository.insertTargets(revision, targetVersionId, carried);
        log.info("disclosure exclusion carried {} targets from {} to {} at revision {}", carried.size(), baseVersionId,
                targetVersionId, revision);
        return carried.size();
    }
}
