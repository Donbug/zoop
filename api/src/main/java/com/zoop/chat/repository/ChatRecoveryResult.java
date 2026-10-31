package com.zoop.chat.repository;

/** One {@code chat_recovery_results} row: a verified result as JSON text, with its route summary when the run had one. */
public record ChatRecoveryResult(String result, String routeSummary) {
}
