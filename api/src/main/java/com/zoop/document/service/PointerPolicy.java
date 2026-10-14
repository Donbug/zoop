package com.zoop.document.service;

/**
 * What an import may do to {@code articles.current_version}. The pointer is never inferred from observation, publication
 * or replay order: it moves only through an explicit compare-and-set to the imported version itself.
 *
 * @param move     false: leave the pointer alone (insertion only)
 * @param expected with {@code move}: the value the pointer must currently have; null means "no current version"
 */
public record PointerPolicy(boolean move, String expected) {
    private static final PointerPolicy KEEP = new PointerPolicy(false, null);

    public static PointerPolicy keep() {
        return KEEP;
    }

    public static PointerPolicy moveFrom(String expected) {
        return new PointerPolicy(true, expected);
    }
}
