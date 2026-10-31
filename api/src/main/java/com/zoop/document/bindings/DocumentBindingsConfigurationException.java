package com.zoop.document.bindings;

/** Startup failure of an enabled export; names the setting that is wrong, never its value. */
public final class DocumentBindingsConfigurationException extends IllegalStateException {
    DocumentBindingsConfigurationException(String setting, String rule) {
        super("zoop.document-bindings." + setting + " " + rule);
    }
}
