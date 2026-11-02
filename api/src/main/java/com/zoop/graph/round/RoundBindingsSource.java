package com.zoop.graph.round;

/**
 * The app's document bindings for a freeze request (A-10): every registered version ({@code DocumentBindingsScope.ALL}), because
 * the bindings are an input of the AI freeze and the window it will choose is not known before it (#407 app change 6). The
 * bytes are the exact {@code zoop-app-document-bindings-1} export.
 */
@FunctionalInterface
public interface RoundBindingsSource {
    /** @throws com.zoop.document.bindings.DocumentBindingsException when the registry cannot be read or the limits are exceeded */
    byte[] export();
}
