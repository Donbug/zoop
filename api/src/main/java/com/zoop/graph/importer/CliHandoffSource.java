package com.zoop.graph.importer;

import com.zoop.graph.importer.HandoffExportParser.VerifiedHandoff;

/** The installed CLI's export envelope, parsed and verified by {@link HandoffExportParser}. */
public final class CliHandoffSource implements HandoffSource {
    private final HandoffExporter exporter;
    private final HandoffExportParser parser;

    public CliHandoffSource(HandoffExporter exporter) {
        this(exporter, new HandoffExportParser());
    }

    CliHandoffSource(HandoffExporter exporter, HandoffExportParser parser) {
        this.exporter = exporter;
        this.parser = parser;
    }

    @Override
    public VerifiedHandoff fetch(GraphHandoffRequest request) {
        return parser.parse(exporter.export(request.handoffId()), request);
    }

    /** The CLI has no content-free route: the export runs again and only its digests are used. */
    @Override
    public Current current(GraphHandoffRequest request) {
        VerifiedHandoff again = fetch(request);
        return new Current(again.manifestDigest(), again.bundleDigest());
    }
}
