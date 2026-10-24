package com.zoop.graph.read;

/**
 * Reads the current public exclusion overlay of one graph version once per request. Exclusions are per version (the producer may
 * reuse an id in a corrected later handoff, which a global set would hide too); the store is {@code disclosure_exclusion_*},
 * written only by the operator exclusion command ({@code com.zoop.graph.exclusion}). A reader never reports a withdrawal as done by
 * itself: it reports what the store holds.
 */
public interface DisclosureExclusionReader {
    DisclosureExclusions current(String versionId);

    /** False for a reader without a store: "nothing excluded" is then unknown, not checked (activation gate, FS059). */
    default boolean authoritative() {
        return true;
    }
}
