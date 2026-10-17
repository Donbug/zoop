package com.zoop.company.graph;

import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class CompanyGraphSnapshotConfiguration {
    @Bean
    @ConditionalOnMissingBean(CompanyGraphSnapshotReader.class)
    CompanyGraphSnapshotReader unavailableCompanyGraphSnapshotReader() {
        return request -> java.util.Optional.empty();
    }
}
