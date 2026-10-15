package com.zoop.document.evidence.config;

/** Startup failure of the document read settings; names the setting that is wrong, never its value. */
public final class DocumentReadConfigurationException extends IllegalStateException {
    DocumentReadConfigurationException(String setting, String rule) {
        super("zoop.document-read." + setting + " " + rule);
    }
}
