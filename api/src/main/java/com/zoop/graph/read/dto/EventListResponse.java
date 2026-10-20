package com.zoop.graph.read.dto;

import java.util.List;

/** OpenAPI {@code EventListResponse} ({@code listEvents}); every key is serialized, nulls included. */
public record EventListResponse(List<EventSummary> items, List<EventSummary> unknownTimeItems, Metadata metadata,
        String nextCursor) {

    /**
     * relationTypes: the direct approved edge types between the requested company and this event only. assertionStatus:
     * the AI handoff issue's status as given (occurred, announced, planned, forecast, cancelled, unknown), null when the
     * snapshot has none.
     */
    public record EventSummary(String title, String id, String action, String target, String eventTime,
            String timePrecision, String period, String assertionStatus, List<String> companyIds, List<String> relationTypes, int articleCount,
            String reportedAt) { }

    public record Metadata(String source, String asOf, String graphVersion, int total, int excludedUnknownTime,
            String latestEventTime, String latestReportedAt) { }
}
