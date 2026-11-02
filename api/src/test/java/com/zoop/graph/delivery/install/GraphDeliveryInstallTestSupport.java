package com.zoop.graph.delivery.install;

/** Keeps installer settings and execution package-private while integration fixtures live with their importers. */
public final class GraphDeliveryInstallTestSupport {
    private GraphDeliveryInstallTestSupport() { }

    public static String install(GraphDeliveryInstaller installer, GraphDeliveryInstallProperties properties,
            String ingestionSources, Runnable schemaValidation) {
        return installer.install(GraphDeliveryInstallSettings.of(properties, ingestionSources), schemaValidation);
    }
}
