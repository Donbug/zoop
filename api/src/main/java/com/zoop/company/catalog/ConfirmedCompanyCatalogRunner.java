package com.zoop.company.catalog;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.context.annotation.Profile;
import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Component;

/** Reconciles the bundled catalog after Flyway, including when the JSON changes. */
@Component
@Profile("!catalog-import")
public class ConfirmedCompanyCatalogRunner implements ApplicationRunner {
    private static final Logger log = LoggerFactory.getLogger(ConfirmedCompanyCatalogRunner.class);
    private final CompanyCatalogImportService importer;

    public ConfirmedCompanyCatalogRunner(CompanyCatalogImportService importer) {
        this.importer = importer;
    }

    @Override
    public void run(ApplicationArguments arguments) {
        var result = importer.importResource(new ClassPathResource("company/demo-companies.json"));
        log.info("Confirmed company catalog ready: total={}, changed={}, unchanged={}",
                result.total(), result.changed(), result.unchanged());
    }
}
