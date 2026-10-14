package com.zoop.document.repository;

/** The columns of {@code articles} the registration reads; identity columns that are always NULL here are not mapped. */
public record ArticleRow(String id, String kind, String provider, String currentVersion, String accessStatus) {
}
