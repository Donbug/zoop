package com.zoop.ai;

/** Invalid AI client settings. The message names the setting, never its value. */
public final class AiClientConfigurationException extends IllegalStateException {
    private final String setting;

    public AiClientConfigurationException(String setting, String problem) {
        super("zoop.ai.client." + setting + " " + problem);
        this.setting = setting;
    }

    public String setting() {
        return setting;
    }
}
