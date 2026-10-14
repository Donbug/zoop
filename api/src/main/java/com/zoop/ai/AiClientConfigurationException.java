package com.zoop.ai;

/**
 * Invalid AI client settings. The message names the setting, never its value. The S1 client's settings live under
 * {@code zoop.ai.client}; the S2 and S3 clients re-report the same failure under their own prefix with {@link #under}.
 */
public final class AiClientConfigurationException extends IllegalStateException {
    private static final String S1_PREFIX = "zoop.ai.client";

    private final String setting;
    private final String problem;

    public AiClientConfigurationException(String setting, String problem) {
        this(S1_PREFIX, setting, problem);
    }

    private AiClientConfigurationException(String prefix, String setting, String problem) {
        super(prefix + "." + setting + " " + problem);
        this.setting = setting;
        this.problem = problem;
    }

    public String setting() {
        return setting;
    }

    /** The same failure reported under another property prefix, for example {@code zoop.ai.extraction-client}. */
    public AiClientConfigurationException under(String prefix) {
        return new AiClientConfigurationException(prefix, setting, problem);
    }
}
