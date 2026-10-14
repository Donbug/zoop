package com.zoop.company.repository;

/** The last sort key returned by a catalog query. */
public record CompanySearchPosition(int rank, String name, String id) {
}
