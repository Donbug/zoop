package com.zoop.company.catalog;

import java.nio.file.Path;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Component;

/** Runs only when explicitly selected with the catalog-import profile and file path. */
@Component
@Profile("catalog-import")
public class CompanyCatalogImportRunner implements ApplicationRunner {
    private static final Logger log = LoggerFactory.getLogger(CompanyCatalogImportRunner.class);
    private final CompanyCatalogImportService importer;
    private final String file;

    public CompanyCatalogImportRunner(CompanyCatalogImportService importer,
                                      @Value("${zoop.catalog.import-file:}") String file) {
        this.importer = importer;
        this.file = file;
    }

    @Override
    public void run(ApplicationArguments arguments) {
        if (file.isBlank()) {
            throw new IllegalArgumentException("Set --zoop.catalog.import-file to a company catalog JSON file");
        }
        var result = importer.importFile(Path.of(file));
        log.info("Company catalog import completed: total={}, changed={}, unchanged={}",
                result.total(), result.changed(), result.unchanged());
    }
}
