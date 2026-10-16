package com.zoop.company.graph;

import java.time.Instant;

/** Version selectors supplied by getCompany. Null selectors mean the caller requested the current view. */
public record CompanyGraphReadRequest(String companyId, String round, String graphVersion, Instant asOf) { }
