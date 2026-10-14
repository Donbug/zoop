package com.zoop.document.analysis.service;

/** A committed pending analysis with its issued AI job id. */
public record Reservation(String analysisId, String aiJobId, long requestNo, String stage) {
}
