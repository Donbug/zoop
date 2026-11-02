package com.zoop.graph.round;

/** A {@code zoop.graph.round.*} setting that cannot be used; the message names the setting, never its value. */
public final class GraphRoundConfigurationException extends IllegalStateException {
    private final String setting;

    public GraphRoundConfigurationException(String setting, String message) {
        super("zoop.graph.round." + setting + " " + message);
        this.setting = setting;
    }

    public String setting() {
        return setting;
    }
}
