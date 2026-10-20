package com.zoop.graph.importer;

/** Startup failure of the graph handoff import settings; names the setting that is wrong, never its value. */
public final class GraphHandoffImportConfigurationException extends IllegalStateException {
    public GraphHandoffImportConfigurationException(String setting, String rule) {
        super("zoop.graph-handoff-import." + setting + " " + rule);
    }
}
