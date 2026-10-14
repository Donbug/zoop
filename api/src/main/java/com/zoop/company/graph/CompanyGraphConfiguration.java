package com.zoop.company.graph;

import java.time.Instant;
import java.util.List;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration(proxyBeanMethods = false)
public class CompanyGraphConfiguration {
    @Bean
    @ConditionalOnMissingBean(CompanyIssueCountQuery.class)
    CompanyIssueCountQuery unavailableCompanyIssueCountQuery() {
        return (List<String> companyIds, String graphVersion, Instant asOf) -> {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        };
    }
}
