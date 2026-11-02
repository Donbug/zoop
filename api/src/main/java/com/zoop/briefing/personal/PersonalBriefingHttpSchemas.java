package com.zoop.briefing.personal;
import io.swagger.v3.oas.annotations.media.Schema;
import java.util.List;
import java.time.Instant;

public final class PersonalBriefingHttpSchemas {
    private PersonalBriefingHttpSchemas() {}
    @Schema(name="PersonalBriefingSelection")
    public record Selection(String roundId,Instant dataAsOf,String policyVersion,Instant basisObservedAt,Basis basis,
        @Schema(nullable=true) String poolVersion, @Schema(nullable=true) String scope,
        @Schema(allowableValues={"available","no_companies","pool_unavailable","no_matching_issues","sources_unavailable"}) String status,
        @Schema(nullable=true) String message,int eligibleCount,int matchingCount,int excludedByCurrentAccess,
        List<Item> items,@Schema(nullable=true) String previousRoundId,String trackingStatus,List<Tracking> tracking) {}
    public record Basis(List<String> holdings,List<String> watchlist,String holdingsKind) {}
    public record Item(String issueId,String title,int importance,String whyImportant,String whyNow,
        @Schema(nullable=true) String analysis,@Schema(nullable=true) String nextCheck,List<Match> matches,List<Source> sources) {}
    public record Match(String companyId,String name,String reason,String directness,List<String> kinds) {}
    public record Source(String evidenceId,String quote,String url,Instant publishedAt) {}
    public record Tracking(String issueId,String title,String companyId,String companyName,String status,String message,
        @Schema(nullable=true) String nextCheck,String basis) {}
}
