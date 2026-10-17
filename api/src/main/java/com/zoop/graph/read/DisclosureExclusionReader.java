package com.zoop.graph.read;

/**
 * Reads the current public exclusion overlay once per request. The default bean reports no exclusions because no
 * exclusion store exists yet (FS081 withdrawal/mislink handling is a later slice); it never reports success of a
 * withdrawal by itself.
 */
public interface DisclosureExclusionReader {
    DisclosureExclusions current();
}
