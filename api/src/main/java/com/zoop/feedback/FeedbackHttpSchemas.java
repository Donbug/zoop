package com.zoop.feedback;

import io.swagger.v3.oas.annotations.media.Schema;
import java.time.Instant;
import java.time.LocalDate;
import java.util.List;

/** Swagger projections; runtime validation remains strict in MemberFeedbackService. */
public final class FeedbackHttpSchemas {
  private FeedbackHttpSchemas() {}

  @Schema(
      name = "FeedbackVote",
      requiredProperties = {"feature", "targetId", "value"})
  public record Vote(
      @Schema(allowableValues = {"briefing_round", "briefing_issue", "chatbot_answer", "news_summary"}) String feature,
      @Schema(minLength = 1, maxLength = 600) String targetId,
      @Schema(
              nullable = true,
              description = "BriefingResponse.feedbackVersion; required for briefing ratings")
          String targetVersion,
      @Schema(allowableValues = {"up", "down", "none"}) String value,
      @Schema(nullable = true, maxLength = 200, description = "Optional, down only")
          String reason) {}

  @Schema(
      name = "FeedbackItem",
      requiredProperties = {"feature", "targetId", "targetVersion", "value", "reason"})
  public record Item(
      String feature,
      String targetId,
      String targetVersion,
      String value,
      @Schema(nullable = true) String reason) {}

  @Schema(
      name = "FeedbackList",
      requiredProperties = {"items", "nextCursor"})
  public record Page(List<Item> items, @Schema(nullable = true) String nextCursor) {}

  @Schema(
      name = "FeedbackDay",
      requiredProperties = {"date", "up", "down", "rate"})
  public record Day(LocalDate date, long up, long down, @Schema(nullable = true) Double rate) {}

  @Schema(
      name = "FeedbackFeatureStat",
      requiredProperties = {
        "feature",
        "label",
        "up",
        "down",
        "total",
        "rate",
        "sampleHidden",
        "days"
      })
  public record Stat(
      String feature,
      String label,
      long up,
      long down,
      long total,
      @Schema(nullable = true) Double rate,
      boolean sampleHidden,
      List<Day> days) {}

  @Schema(
      name = "UnsupportedFeedbackFeature",
      requiredProperties = {"feature", "label", "reason"})
  public record Unsupported(String feature, String label, String reason) {}

  @Schema(
      name = "FeedbackSummary",
      requiredProperties = {
        "window",
        "start",
        "end",
        "asOf",
        "minSample",
        "features",
        "unsupported",
        "basis"
      })
  public record Summary(
      String window,
      @Schema(nullable = true) String start,
      @Schema(nullable = true) String end,
      Instant asOf,
      int minSample,
      List<Stat> features,
      List<Unsupported> unsupported,
      String basis) {}

  @Schema(
      name = "DislikeRow",
      requiredProperties = {
        "at",
        "feature",
        "featureLabel",
        "targetId",
        "targetLabel",
        "reason",
        "voter",
        "sessionId"
      })
  public record Dislike(
      Instant at,
      String feature,
      String featureLabel,
      String targetId,
      String targetLabel,
      @Schema(nullable = true) String reason,
      String voter,
      @Schema(nullable = true) String sessionId) {}

  @Schema(
      name = "DislikePage",
      requiredProperties = {"items", "nextCursor", "total"})
  public record Dislikes(
      List<Dislike> items, @Schema(nullable = true) String nextCursor, long total) {}
}
