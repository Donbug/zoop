package com.zoop.briefing.query;

import com.zoop.briefing.storage.BriefingRound;

/** The source/rights owner supplies the current-grant check, never a cached publication-time permission. */
@FunctionalInterface
public interface BriefingContentAccess {
    boolean mayRead(BriefingRound round);
}
