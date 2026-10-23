package com.zoop.briefing.replay;

import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import java.util.Map;
import java.nio.file.*;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.node.ObjectNode;
import static org.assertj.core.api.Assertions.*;

class BriefingSeriesPriceRulesTest {
    @TempDir Path output;
    private ObjectNode company() {
        var c=StrictJson.newObject().put("roundId","authored-round").put("status","PASS")
            .put("cutoff","2026-10-22T00:20:00Z").put("resultVersion","original-outlook")
            .put("generatedAt","2026-10-22T00:30:00Z");
        c.putObject("frozen").putArray("targets").addObject().put("companyId","NASDAQ:META"); return c;
    }
    private ObjectNode bundle() {
        var bundle=StrictJson.newObject();bundle.putObject("marketEnrichment").put("original","unchanged");
        String sha=Canonical.digest(bundle);
        try { Files.write(output.resolve("prices-baseline.json"),Canonical.bytes(bundle)); } catch(Exception e) { throw new RuntimeException(e); }
        var layer=((ObjectNode)bundle.path("marketEnrichment")).putObject("seriesCompanyPrices")
            .put("schemaVersion",BriefingSeriesPriceRules.SCHEMA).put("authorizationRef","local:authored")
            .put("baseBundleSha256",sha).put("period1",1792022400).put("period2",1792713600);
        var row=layer.putArray("rounds").addObject().put("roundId","authored-round").put("cutoff","2026-10-22T00:20:00Z")
            .put("companyResultVersion","original-outlook").put("recordedAt","2026-10-22T01:00:00Z");
        var sources=row.putObject("prices").putObject("NASDAQ:META").putArray("sources");
        for(String interval:new String[]{"5m","1d"})sources.addObject().put("interval",interval)
            .put("period1",1792022400).put("period2",1792713600).put("collectedAt","2026-10-22T00:55:00Z");
        version(row);return bundle;
    }
    private void version(ObjectNode row) { row.remove("resultVersion");row.put("resultVersion","company-prices-v1-"+Canonical.digest(row)); }
    private Map<String,StrictJson.Obj> originals(){return Map.of("authored-round",StrictJson.Obj.of(company()));}
    @Test void priceLayerBindsOriginalBundleOutlookAndCompleteCompanySet() {
        var b=bundle();assertThat(BriefingSeriesPriceRules.rows(StrictJson.Obj.of(b),"local:authored",originals(),output)).hasSize(1);
        ((ObjectNode)b.path("marketEnrichment")).put("original","changed");
        assertThatThrownBy(()->BriefingSeriesPriceRules.rows(StrictJson.Obj.of(b),"local:authored",originals(),output))
            .hasMessageContaining("base_bundle");
    }
    @Test void newPriceVersionCannotHideAnotherOutlookCompanyOrRange() {
        for(String field:new String[]{"companyResultVersion","company","range","clock"}) {
            var b=bundle();var row=(ObjectNode)b.path("marketEnrichment").path("seriesCompanyPrices").path("rounds").get(0);
            switch(field){
                case "companyResultVersion" -> row.put(field,"other");
                case "company" -> ((ObjectNode)row.path("prices")).putObject("NASDAQ:AMD");
                case "range" -> ((ObjectNode)row.path("prices").path("NASDAQ:META").path("sources").get(0)).put("period1",1791936000);
                default -> row.put("recordedAt","2026-10-22T00:10:00Z");
            }
            version(row);
            assertThatThrownBy(()->BriefingSeriesPriceRules.rows(StrictJson.Obj.of(b),"local:authored",originals(),output))
                .isInstanceOf(IllegalArgumentException.class);
        }
    }
}
