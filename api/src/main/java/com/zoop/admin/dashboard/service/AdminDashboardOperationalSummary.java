package com.zoop.admin.dashboard.service;

import tools.jackson.databind.ObjectMapper;
import com.zoop.admin.ai.AiUsageService;
import com.zoop.admin.briefings.AdminBriefingService;
import com.zoop.admin.dashboard.dto.AdminDashboardResponse;
import com.zoop.common.response.Metadata;
import java.util.ArrayList;
import org.springframework.stereotype.Service;

/** Reuse the same guarded read models on the landing page; failures remain independent. */
@Service
public class AdminDashboardOperationalSummary {
    private final AdminBriefingService briefings;private final AiUsageService ai;private final ObjectMapper mapper=new ObjectMapper();private final org.springframework.jdbc.core.JdbcTemplate jdbc;
    public AdminDashboardOperationalSummary(AdminBriefingService briefings,AiUsageService ai,org.springframework.jdbc.core.JdbcTemplate jdbc){this.briefings=briefings;this.ai=ai;this.jdbc=jdbc;}
    public AdminDashboardResponse enrich(AdminDashboardResponse base,String admin){
        var failures=new ArrayList<>(base.metadata().failures());
        tools.jackson.databind.JsonNode rounds=null,usage=null;
        try{
            var list=briefings.list(admin,null,null,null,5);var node=mapper.createObjectNode();
            node.set("latest",mapper.readTree(list.path("items").toString()));
            long delayed=jdbc.queryForObject("SELECT count(*) FROM briefing_rounds WHERE status='failed' OR (status IN ('scheduled','generating','verifying') AND scheduled_at<?)",Long.class,java.sql.Timestamp.from(base.generatedAt()));
            node.put("delayedOrFailed",delayed);rounds=node;failures.removeIf(f->f.section().equals("briefings"));
        }catch(Exception ignored){/* The existing per-section unavailable response remains. */}
        try{
            var source=ai.getUsage("7d");var node=mapper.createObjectNode().put("window","7d");
            Long requests=0L,succeeded=0L,failed=0L;var features=node.putArray("features");
            for(var feature:source.features()){
                requests=requests==null||feature.requests()==null?null:requests+feature.requests();
                succeeded=succeeded==null||feature.succeeded()==null?null:succeeded+feature.succeeded();
                failed=failed==null||feature.failed()==null?null:failed+feature.failed();
                var item=features.addObject().put("feature",feature.feature()).put("label",feature.label());item.put("requests",feature.requests());item.put("failed",feature.failed());
            }
            node.put("requests",requests);node.put("succeeded",succeeded);node.put("failed",failed);usage=node;failures.removeIf(f->f.section().equals("ai"));
        }catch(Exception ignored){/* Unknown is never converted to zero. */}
        var m=base.metadata();var metadata=new Metadata(m.source(),m.asOf(),m.graphVersion(),m.requestId(),!failures.isEmpty(),java.util.List.copyOf(failures));
        return new AdminDashboardResponse(base.generatedAt(),metadata,base.ledger(),base.graph(),base.candidates(),base.jobs(),usage,rounds,base.members(),base.audit());
    }
}
