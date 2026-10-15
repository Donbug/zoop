package com.zoop.document.analysis;

/** Startup failure of an enabled analysis; names the setting that is wrong, never its value. */
public final class DocumentAnalysisConfigurationException extends IllegalStateException {
    DocumentAnalysisConfigurationException(String setting, String rule) {
        super("zoop.document-analysis." + setting + " " + rule);
    }
}
