package com.zoop.chat.service;

import java.util.List;

/**
 * The selection a question was asked with, kept unchanged next to the public {@code ChatFrozenContext}
 * ({@code chat_jobs.frozen_selection}). The public context only shows labels and a capped evidence count; this keeps what an
 * execution needs to reproduce the same scope: the requested {@code contextIds} and {@code evidenceIds} as sent, and the
 * resolved {@code evidencePool} (the visible evidence of the selected targets, narrowed to {@code evidenceIds} when both were
 * given) in the pinned graph version. A clarification reply copies its original's selection.
 */
public record FrozenSelection(List<String> contextIds, List<String> evidenceIds, List<String> evidencePool) {
    public static final FrozenSelection NONE = new FrozenSelection(List.of(), List.of(), List.of());
}
