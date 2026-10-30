package com.zoop.document.bindings;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

/**
 * {@code zoop.document-bindings.*}, normally set from {@code ZOOP_DOCUMENT_BINDINGS_*} environment variables (see
 * {@code application.yml}). Disabled unless {@code enabled=true}; when enabled {@link #toSettings()} validates every value at
 * startup.
 */
@ConfigurationProperties("zoop.document-bindings")
public record DocumentBindingsProperties(
        @DefaultValue("false") boolean enabled,
        String output,
        String result,
        String selection,
        @DefaultValue("available") String scope) {

    public DocumentBindingsSettings toSettings() {
        return DocumentBindingsSettings.of(output, result, selection, scope);
    }

    @Override
    public String toString() {
        return "DocumentBindingsProperties[enabled=" + enabled + "]";
    }
}
