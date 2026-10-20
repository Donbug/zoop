package com.zoop.briefing.query;

import com.zoop.briefing.storage.BriefingRound;

/** Current source authority for a fixed publication; publication-time permission alone is insufficient. */
@FunctionalInterface
public interface BriefingContentAccess {
    boolean mayRead(BriefingRound round, String requestId);
}
