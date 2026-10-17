package com.zoop.company.market;

import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Configuration;

@Configuration
@EnableConfigurationProperties(CompanyMarketSettings.class)
public class MarketDataConfiguration { }
