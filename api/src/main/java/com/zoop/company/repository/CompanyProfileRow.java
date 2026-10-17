package com.zoop.company.repository;

import java.util.List;

public record CompanyProfileRow(String id, String name, String ticker, String exchangeCode, String market,
        List<String> aliases, String brandColor, String logoUrl, String legalName, String representative,
        String foundedDate, String websiteUrl, String sector) {
}
