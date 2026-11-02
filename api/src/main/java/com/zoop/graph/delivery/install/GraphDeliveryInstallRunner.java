package com.zoop.graph.delivery.install;

import javax.sql.DataSource;
import com.zoop.common.json.StrictJson;
import com.zoop.graph.delivery.GraphDeliveryException;
import com.zoop.graph.delivery.GraphDeliveryResultFile;
import com.zoop.graph.delivery.GraphDeliverySchemaGuard;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.core.env.Environment;

/** Exclusive result reservation preserves the distinction between a recorded refusal and an unknown outcome. */
public final class GraphDeliveryInstallRunner implements ApplicationRunner {
    private static final Logger log = LoggerFactory.getLogger(GraphDeliveryInstallRunner.class);
    private final GraphDeliveryInstallSettings settings;
    private final GraphDeliveryInstaller installer;
    private final DataSource dataSource;
    private final Environment environment;

    GraphDeliveryInstallRunner(GraphDeliveryInstallSettings settings, GraphDeliveryInstaller installer,
            DataSource dataSource, Environment environment) {
        this.settings = settings;
        this.installer = installer;
        this.dataSource = dataSource;
        this.environment = environment;
    }

    @Override
    public void run(ApplicationArguments arguments) {
        try (var result = GraphDeliveryResultFile.reserve(settings.result())) {
            var body = StrictJson.newObject();
            body.put("schemaVersion", "zoop-graph-delivery-install-result-1");
            body.put("versionId", settings.versionId());
            body.put("destinationId", settings.destinationId());
            body.put("packageDigest", settings.expectedPackageDigest());
            String failure = null;
            try {
                String outcome = installer.install(settings, () -> GraphDeliverySchemaGuard.validate(dataSource, environment));
                body.put("status", "succeeded");
                body.put("outcome", outcome);
                body.put("outcomeKnown", true);
                body.put("activation", "not-requested");
            } catch (GraphDeliveryException refused) {
                failure = refused.code();
            } catch (RuntimeException error) {
                log.error("graph delivery install failed: {}", error.getClass().getSimpleName());
                failure = "internal_error";
            }
            if (failure != null) {
                body.put("status", "failed");
                body.putObject("failure").put("code", failure);
                body.put("outcomeKnown", !failure.equals("database_unavailable") && !failure.equals("internal_error")
                        && !failure.equals("artifact_unavailable"));
            }
            result.write(body);
            if (failure != null) throw new GraphDeliveryException(failure);
        }
    }
}
