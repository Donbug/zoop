package com.zoop.graph.exclusion;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

import com.zoop.graph.exclusion.ExclusionRequest.Target;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Carries the public version's unlifted exclusions to the original versions an activation makes public for the first time (#55
 * A-14, FS081). Exclusions belong to original (source) versions: a cumulative publication reads the exclusions of every source it
 * retains, so a retained source keeps its own. What a new source does not have is the decision the operator took on the sources
 * public until now; without this, an exclusion would end the moment a later round's source holding the same id is activated.
 * Runs inside the activation transaction, under the publication lock the activation holds, before the activation reads the new
 * version's overlay: the carried targets are then part of the pre-activation checks, and a refused activation rolls them back.
 * <p>
 * The carry never writes to a cumulative publication's own id: a lift names an original version (a composite lift is refused),
 * so a row there could never end. Each carried change instead names, in {@code base_version_id}, the original version whose
 * current exclusion it copies, and goes to each new source of the target: a source of {@code targetSources} that is not one of
 * {@code baseSources}. A target is carried whether or not the new source holds the id: a lift is the only end of an exclusion
 * (exposure consumption rule 4), and an absent id filters nothing. A target the operator lifted on the new source itself (its
 * latest change there is a lift) is not carried over that decision, and one already excluded there is not carried again, so a
 * re-activation or a retried activation appends nothing twice. A lift on the original version is not carried either; a lift with
 * {@code laterVersions} on that original version also ends the copies on the original versions imported after it.
 */
public class DisclosureExclusionCarry {
    public static final String CAUSE = "carried";
    private static final Logger log = LoggerFactory.getLogger(DisclosureExclusionCarry.class);

    private final JdbcDisclosureExclusionRepository repository;

    public DisclosureExclusionCarry(JdbcDisclosureExclusionRepository repository) {
        this.repository = repository;
    }

    /**
     * Appends one carried change per base source that has something to carry and returns how many target rows it wrote (0:
     * nothing written). {@code baseSources} are the original versions of the version public until now, {@code targetSources}
     * those of the version being activated, both in contribution order. {@code activatedBy} names the activation's actor for the
     * change's reason ({@code system} or {@code admin:<id>}); the change's operator is always {@code system}. Must run under the
     * publication lock, in the activation's transaction.
     */
    public int carry(List<String> baseSources, List<String> targetSources, String activatedBy) {
        List<String> fresh = targetSources.stream().filter(source -> !baseSources.contains(source)).distinct().toList();
        if (baseSources.isEmpty() || fresh.isEmpty()) return 0;
        Map<String, Set<Target>> taken = new HashMap<>();
        for (String target : fresh) {
            Set<Target> skip = new LinkedHashSet<>(repository.excluded(target));
            skip.addAll(repository.lifted(target));
            taken.put(target, skip);
        }
        int written = 0;
        for (String base : baseSources.stream().distinct().toList()) {
            Set<Target> excluded = repository.excluded(base);
            if (excluded.isEmpty()) continue;
            Map<String, List<Target>> rows = new LinkedHashMap<>();
            for (String target : fresh) {
                Set<Target> skip = taken.get(target);
                List<Target> carried = new ArrayList<>();
                for (Target candidate : excluded) {
                    // A target several base sources exclude is carried once, from the first of them.
                    if (skip.add(candidate)) carried.add(candidate);
                }
                if (!carried.isEmpty()) rows.put(target, carried);
            }
            if (rows.isEmpty()) continue;
            long revision = repository.revision() + 1;
            repository.insertChange(revision, "exclude", CAUSE, null, base,
                    "carried from " + base + " at activation by " + activatedBy, "system");
            for (Map.Entry<String, List<Target>> entry : rows.entrySet()) {
                repository.insertTargets(revision, entry.getKey(), entry.getValue());
                written += entry.getValue().size();
                log.info("disclosure exclusion carried {} targets from {} to {} at revision {}", entry.getValue().size(), base,
                        entry.getKey(), revision);
            }
        }
        return written;
    }
}
