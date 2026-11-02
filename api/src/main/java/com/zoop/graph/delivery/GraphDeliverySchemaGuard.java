package com.zoop.graph.delivery;

import javax.sql.DataSource;
import org.flywaydb.core.Flyway;
import org.springframework.core.env.Environment;

/** Startup guards run before singleton initialization; delivery commands only validate an already-applied schema. */
public final class GraphDeliverySchemaGuard {
    private GraphDeliverySchemaGuard() { }

    public static void requireNoMigration(Environment environment) {
        if (!"false".equalsIgnoreCase(environment.getProperty("spring.flyway.enabled"))
                || !"validate".equalsIgnoreCase(environment.getProperty("spring.jpa.hibernate.ddl-auto", "validate"))
                || !"never".equalsIgnoreCase(environment.getProperty("spring.sql.init.mode", "never"))) {
            throw new GraphDeliveryException("schema_mismatch");
        }
    }

    public static void validate(DataSource dataSource, Environment environment) {
        requireNoMigration(environment);
        try {
            Flyway flyway = Flyway.configure().dataSource(dataSource).locations("classpath:db/migration")
                    .ignoreMigrationPatterns(new String[0]).skipDefaultCallbacks(true).load();
            flyway.validate();
            if (flyway.info().current() == null || flyway.info().pending().length != 0) {
                throw new GraphDeliveryException("schema_mismatch");
            }
        } catch (RuntimeException mismatch) {
            throw new GraphDeliveryException("schema_mismatch");
        }
    }
}
