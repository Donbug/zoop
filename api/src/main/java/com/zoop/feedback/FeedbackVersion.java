package com.zoop.feedback;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

/** A graph-less immutable publication still has an exact version; never fabricate a graph ID. */
@Component
public class FeedbackVersion {
  public static final String SQL = "COALESCE(r.graph_version_id,'publication:'||r.payload_sha256)";
  private final JdbcTemplate jdbc;

  public FeedbackVersion(JdbcTemplate jdbc) {
    this.jdbc = jdbc;
  }

  public String get(String roundId) {
    return jdbc.queryForObject(
        "SELECT " + SQL + " FROM briefing_rounds r WHERE id=? AND r.published_at IS NOT NULL",
        String.class,
        roundId);
  }
}
