package com.zoop.graph.delivery.install;

import java.nio.file.Files;
import java.nio.file.Path;
import com.zoop.document.evidence.config.DocumentReadConfigurationException;
import com.zoop.document.evidence.config.DocumentReadProperties;
import com.zoop.graph.delivery.GraphDeliveryException;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.boot.test.context.runner.WebApplicationContextRunner;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.core.env.StandardEnvironment;
import static org.junit.jupiter.api.Assertions.*;

class GraphDeliveryInstallConfigurationTest {
    @TempDir Path temp;

    private static void isolate(ConfigurableApplicationContext context) {
        context.getEnvironment().getPropertySources().remove(StandardEnvironment.SYSTEM_ENVIRONMENT_PROPERTY_SOURCE_NAME);
        context.getEnvironment().getPropertySources().remove(StandardEnvironment.SYSTEM_PROPERTIES_PROPERTY_SOURCE_NAME);
    }

    private String[] valid() throws Exception {
        Path root = Files.createDirectory(temp.toRealPath().resolve("artifacts"));
        return new String[] {"zoop.graph-delivery.install.enabled=true", "spring.flyway.enabled=false",
                "zoop.graph-delivery.install.destination-id=serving-test", "zoop.graph-delivery.install.version-id=gv-" + "a".repeat(64),
                "zoop.graph-delivery.install.expected-package-digest=" + "b".repeat(64),
                "zoop.graph-delivery.install.artifact-root=" + root, "zoop.graph-delivery.install.result=" + temp.resolve("result.json")};
    }

    @Test void webPlusInstallRefusesBeforeRunnerOperations() throws Exception {
        new WebApplicationContextRunner().withInitializer(GraphDeliveryInstallConfigurationTest::isolate)
                .withUserConfiguration(GraphDeliveryInstallConfiguration.class).withPropertyValues(valid()).run(context -> {
                    Throwable error = context.getStartupFailure();
                    assertNotNull(error);
                    while (error.getCause() != null) error = error.getCause();
                    assertInstanceOf(GraphDeliveryException.class, error);
                    assertEquals("configuration_invalid", ((GraphDeliveryException) error).code());
                    assertFalse(Files.exists(temp.resolve("result.json")));
                });
    }

    @Test void ordinaryRegistryConfigurationRemainsStrict() {
        var properties = new DocumentReadProperties(null, temp.resolve("missing.json").toString(), null);
        assertThrows(DocumentReadConfigurationException.class, properties::ingestionSourcesPath);
    }
}
