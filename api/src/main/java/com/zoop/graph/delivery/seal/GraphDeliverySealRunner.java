package com.zoop.graph.delivery.seal;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import javax.sql.DataSource;
import com.zoop.common.json.StrictJson;
import com.zoop.graph.delivery.GraphDeliveryException;
import com.zoop.graph.delivery.GraphDeliveryResultFile;
import com.zoop.graph.delivery.GraphDeliverySchemaGuard;
import com.zoop.graph.delivery.JdbcGraphDeliveryStore;
import com.zoop.graph.importer.GraphHandoffException;
import com.zoop.graph.importer.GraphHandoffImportSettings;
import com.zoop.graph.importer.GraphHandoffRequest;
import com.zoop.graph.importer.GraphHandoffRequestParser;
import com.zoop.graph.version.GraphVersionRepository;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.core.env.Environment;
import org.springframework.dao.DataAccessException;
import org.springframework.transaction.TransactionException;
import tools.jackson.databind.node.ObjectNode;

public final class GraphDeliverySealRunner implements ApplicationRunner {
    private final GraphDeliverySealProperties settings;
    private final ObjectProvider<GraphDeliverySealer> sealer;
    private final ObjectProvider<GraphHandoffImportSettings> imports;
    private final JdbcGraphDeliveryStore deliveries;
    private final GraphVersionRepository versions;
    private final DataSource dataSource;
    private final Environment environment;

    public GraphDeliverySealRunner(GraphDeliverySealProperties settings, ObjectProvider<GraphDeliverySealer> sealer,
            ObjectProvider<GraphHandoffImportSettings> imports, JdbcGraphDeliveryStore deliveries,
            GraphVersionRepository versions, DataSource dataSource, Environment environment) {
        this.settings = settings;
        this.sealer = sealer;
        this.imports = imports;
        this.deliveries = deliveries;
        this.versions = versions;
        this.dataSource = dataSource;
        this.environment = environment;
    }

    @Override
    public void run(ApplicationArguments arguments) {
        try (GraphDeliveryResultFile file = GraphDeliveryResultFile.reserve(settings.resultPath())) {
            ObjectNode result = StrictJson.newObject();
            result.put("schemaVersion", "zoop-graph-delivery-seal-1");
            String failure = null;
            try {
                GraphDeliverySchemaGuard.validate(dataSource, environment);
                result.put("status", "succeeded");
                result.put("destinationId", settings.destinationId());
                if ("status".equals(settings.command())) {
                    status(result);
                } else {
                    var sealed = "seal-publication".equals(settings.command())
                            ? sealer.getObject().sealPublication(publicationRequest(), settings.limits())
                            : sealer.getObject().seal(request(), settings.destinationId(), settings.limits());
                    result.put("outcome", sealed.outcome());
                    result.put("versionId", sealed.versionId());
                    result.put("packageDigest", sealed.packageDigest());
                    result.put("fileCount", sealed.fileCount());
                    result.put("totalBytes", sealed.totalBytes());
                    result.put("activation", "not-requested");
                }
            } catch (GraphDeliveryException refused) {
                failure = refused.code();
            } catch (GraphHandoffException refused) {
                failure = refused.failure().code();
            } catch (DataAccessException | TransactionException unknown) {
                failure = "database_unavailable";
            } catch (RuntimeException unknown) {
                failure = "internal_error";
            }
            if (failure != null) {
                result.removeAll();
                result.put("schemaVersion", "zoop-graph-delivery-seal-1");
                result.put("status", "failed");
                result.putObject("failure").put("code", failure);
                result.put("outcomeKnown", !(failure.equals("database_unavailable") || failure.equals("internal_error")));
            }
            file.write(result);
            if (failure != null) throw new GraphDeliveryException(failure);
        }
    }

    private GraphHandoffRequest request() {
        try (InputStream input = Files.newInputStream(imports.getObject().request())) {
            byte[] bytes = input.readNBytes(GraphHandoffRequestParser.MAX_BYTES + 1);
            if (bytes.length > GraphHandoffRequestParser.MAX_BYTES) throw new GraphDeliveryException("request_invalid");
            return new GraphHandoffRequestParser().parse(bytes);
        } catch (IOException invalid) {
            throw new GraphDeliveryException("request_invalid");
        }
    }

    private GraphPublicationSealRequest publicationRequest() {
        try (InputStream input = Files.newInputStream(settings.requestPath())) {
            var request = GraphPublicationSealRequest.parse(input.readNBytes(GraphPublicationSealRequest.MAX_BYTES + 1));
            if (!settings.destinationId().equals(request.destinationId())) throw new GraphDeliveryException("request_invalid");
            return request;
        } catch (IOException invalid) {
            throw new GraphDeliveryException("request_invalid");
        }
    }

    private void status(ObjectNode result) {
        result.put("outcome", "status");
        var packages = result.putArray("packages");
        for (var row : deliveries.packages(settings.destinationId())) {
            var version = versions.find(row.versionId()).orElseThrow(() -> new GraphDeliveryException("package_invalid"));
            var item = packages.addObject();
            item.put("versionId", row.versionId());
            item.put("sealed", true);
            item.put("packageDigest", row.packageDigest());
            item.put("installed", deliveries.findInstall(row.versionId(), row.destinationId()).isPresent());
            item.put("active", version.active());
            item.put("wasActive", versions.everActivated(row.versionId()));
        }
    }
}
