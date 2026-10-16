package com.zoop.company.service;

import java.time.Instant;
import java.time.LocalDate;
import java.time.format.DateTimeParseException;
import java.util.List;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.response.Metadata;
import com.zoop.common.response.SectionFailure;
import com.zoop.company.graph.CompanyGraphReadRequest;
import com.zoop.company.graph.CompanyGraphSnapshot;
import com.zoop.company.graph.CompanyGraphSnapshotReader;
import com.zoop.company.graph.CompanyGraphSnapshot.CompanyIssueRef;
import com.zoop.company.repository.CompanyProfileRow;
import com.zoop.company.repository.CompanySearchRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class CompanyDetailService {
    private final CompanySearchRepository repository;
    private final CompanyGraphSnapshotReader graphSnapshotReader;

    public CompanyDetailService(CompanySearchRepository repository, CompanyGraphSnapshotReader graphSnapshotReader) {
        this.repository = repository;
        this.graphSnapshotReader = graphSnapshotReader;
    }

    @Transactional(readOnly = true)
    public CompanyDetail getCompany(String id, String round, String graphVersion, String asOf, String requestId) {
        Instant requestStartedAt = Instant.now();
        CompanyProfileRow company = repository.findProfile(id)
                .orElseThrow(() -> new CustomException(ErrorCode.RESOURCE_NOT_FOUND));
        Instant requestedAsOf = parseInstant(asOf);
        var graph = graphSnapshotReader.read(new CompanyGraphReadRequest(id, round, graphVersion, requestedAsOf));
        if (graph.isEmpty() && (round != null || graphVersion != null || asOf != null)) {
            throw new CustomException(ErrorCode.VERSION_UNAVAILABLE);
        }
        if (graph.isPresent()) return detail(company, graph.get(), requestId);

        String unavailableMessage = "공개된 그래프 스냅샷이 없습니다.";
        List<SectionFailure> failures = List.of(
                new SectionFailure("directIssues", "VERSION_UNAVAILABLE", unavailableMessage, false, null),
                new SectionFailure("structuralIssues", "VERSION_UNAVAILABLE", unavailableMessage, false, null),
                new SectionFailure("summary", "VERSION_UNAVAILABLE", unavailableMessage, false, null));
        var summary = new Unavailable("unavailable", "공개된 그래프 요약이 없습니다.");
        return new CompanyDetail(company.id(), company.name(), company.legalName(), company.market(),
                company.representative(), parseDate(company.foundedDate()), company.websiteUrl(), company.ticker(),
                company.aliases(), company.sector(), company.brandColor(), company.logoUrl(), List.of(), List.of(),
                summary, null, null, new Metadata("postgresql", requestStartedAt, null, requestId, true, failures));
    }

    private static CompanyDetail detail(CompanyProfileRow company, CompanyGraphSnapshot graph, String requestId) {
        boolean missingFromGraph = !graph.companyFound();
        List<SectionFailure> failures = graph.summary() == null || missingFromGraph
                ? List.of(new SectionFailure("summary", missingFromGraph ? "GRAPH_COMPANY_NOT_FOUND" : "VERSION_UNAVAILABLE",
                        missingFromGraph ? "선택한 그래프 버전에 기업 정보가 없습니다." : "공개된 그래프 요약이 없습니다.",
                        false, graph.asOf()))
                : List.of();
        Object summary = graph.summary() == null || missingFromGraph
                ? new Unavailable("unavailable", missingFromGraph ? "선택한 그래프 버전에 기업 정보가 없습니다."
                        : "공개된 그래프 요약이 없습니다.")
                : graph.summary();
        return new CompanyDetail(company.id(), company.name(), company.legalName(), company.market(),
                company.representative(), parseDate(company.foundedDate()), company.websiteUrl(), company.ticker(),
                company.aliases(), company.sector(), company.brandColor(), company.logoUrl(),
                missingFromGraph ? List.of() : graph.directIssues(),
                missingFromGraph ? List.of() : graph.structuralIssues(), summary, null, null,
                new Metadata("public_graph_snapshot", graph.asOf(), graph.graphVersion(), requestId,
                        !failures.isEmpty(), failures));
    }

    private static Instant parseInstant(String value) {
        if (value == null || value.isBlank()) return null;
        try { return Instant.parse(value); }
        catch (DateTimeParseException exception) { throw new CustomException(ErrorCode.INVALID_REQUEST, exception); }
    }

    private static LocalDate parseDate(String value) {
        if (value == null || value.isBlank()) return null;
        try { return LocalDate.parse(value); }
        catch (DateTimeParseException exception) { return null; }
    }

    public record Unavailable(String status, String reason) { }
    public record CompanyDetail(String id, String name, String legalName, String market, String representative,
            LocalDate foundedDate, String websiteUrl, String ticker, List<String> aliases, String sector,
            String brandColor, String logoUrl, List<CompanyIssueRef> directIssues, List<CompanyIssueRef> structuralIssues,
            Object summary, Boolean holding, Boolean watch, Metadata metadata) { }
}
