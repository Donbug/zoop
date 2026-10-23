package com.zoop.briefing.replay;

import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import java.time.*;

/** Explicit bounded retrospective sequence, independently bound before any DB write. */
final class BriefingRoundSeriesRules {
    private static final ZoneId KST = ZoneId.of("Asia/Seoul");
    static void validate(StrictJson.Obj bundle) {
        var series = bundle.object("roundSeries");
        require("zoop-briefing-round-series-v1".equals(series.string("schemaVersion"))
                && series.bool("retrospectiveBodies") && !series.bool("productionAuthorized")
                && bundle.string("sourceFileSha256").equals(series.string("sourceFileSha256"))
                && Canonical.digest(series.node()).equals(bundle.object("authorization").string("roundSeriesSha256")), "metadata");
        var specs = series.objects("rounds"); var rows = bundle.objects("rounds");
        require(!specs.isEmpty() && specs.size() <= 14 && specs.size() == rows.size(), "population");
        Instant previous = null;
        for (int i=0; i<rows.size(); i++) {
            var row=rows.get(i); var spec=specs.get(i);
            require(row.string("date").equals(spec.string("date")) && row.string("edition").equals(spec.string("edition"))
                    && row.object("window").node().equals(spec.object("window").node()), "definition");
            var window=spec.object("window"); var date=LocalDate.parse(spec.string("date"));
            boolean am="morning".equals(spec.string("edition"));
            require(am || "evening".equals(spec.string("edition")), "edition");
            Instant end=date.atTime(am ? LocalTime.of(9,20) : LocalTime.of(17,30)).atZone(KST).toInstant();
            Instant start=(am ? date.minusDays(1).atTime(17,30) : date.atTime(9,20)).atZone(KST).toInstant();
            require(!window.bool("openStart") && start.equals(Instant.parse(window.string("from")))
                    && end.equals(Instant.parse(window.string("to"))) && !end.isAfter(Instant.now())
                    && (previous==null || previous.equals(start)), "chronology");
            previous=end; identity(bundle,row);
        }
    }
    static void identity(StrictJson.Obj bundle, StrictJson.Obj round) {
        var id=round.object("identity");
        require(id.object("roundSeries").node().equals(bundle.object("roundSeries").node())
                && id.object("baseline").string("from").equals(bundle.object("roundSeries").objects("rounds").getFirst().object("window").string("from"))
                && "explicit_series_baseline".equals(id.object("baseline").string("meaning")), "identity");
        if (id.has("publicationCompanyIds")) {
            var allowed=java.util.Set.copyOf(id.strings("publicationCompanyIds"));
            require(!allowed.isEmpty(), "catalogue");
            for (var item:round.objects("selected")) for (var link:item.objects("companyLinks"))
                require(allowed.contains(link.string("companyId")), "company_scope");
        }
    }
    private static void require(boolean valid,String code) {
        if (!valid) throw new IllegalArgumentException("Briefing series rejected: "+code);
    }
}
