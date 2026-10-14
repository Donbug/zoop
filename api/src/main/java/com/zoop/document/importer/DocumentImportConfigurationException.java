package com.zoop.document.importer;

/** Startup failure of an enabled import; names the setting that is wrong, never its value. */
public final class DocumentImportConfigurationException extends IllegalStateException {
    DocumentImportConfigurationException(String setting, String rule) {
        super("zoop.document-import." + setting + " " + rule);
    }
}
