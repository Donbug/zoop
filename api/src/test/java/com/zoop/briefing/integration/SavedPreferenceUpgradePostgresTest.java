package com.zoop.briefing.integration;

import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.UUID;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import static org.junit.jupiter.api.Assertions.*;

/** Upgrade a populated pre-scope schema, rather than proving only a fresh database. */
@Tag("briefing-postgres")
@EnabledIfEnvironmentVariable(named="DB_URL",matches="jdbc:postgresql:.*")
class SavedPreferenceUpgradePostgresTest {
    @Test void addsDemoScopeWithoutChangingExistingSettingsDeliveriesPublicationsOrFeedback()throws Exception {
        String url=System.getenv("DB_URL");var address=java.net.URI.create(url.substring(5));
        assertTrue(List.of("localhost","127.0.0.1","[::1]").contains(address.getHost()));assertTrue(address.getPath().contains("test"));
        String schema="demo_upgrade_"+UUID.randomUUID().toString().replace("-","");
        var source=new DriverManagerDataSource(url+(url.contains("?")?"&":"?")+"currentSchema="+schema,
            System.getenv().getOrDefault("DB_USERNAME","briefing_test"),System.getenv().getOrDefault("DB_PASSWORD",""));
        var jdbc=new JdbcTemplate(source);
        try {
            Flyway.configure().dataSource(source).schemas(schema).defaultSchema(schema).outOfOrder(false).target("20261103110000").load().migrate();
            try(var in=getClass().getResourceAsStream("/briefing/fixture.sql")){jdbc.execute(new String(in.readAllBytes(),StandardCharsets.UTF_8));}
            jdbc.update("""
                INSERT INTO members(id,analytics_key,email,email_key,display_name,signup_method,status,created_at,mode,completed,tutorial_completed,settings_version,updated_at)
                VALUES('upgrade-owner','upgrade-owner','scope@example.invalid','scope@example.invalid','[합성] 회원','google','active',now(),'watchlist',true,true,3,now())
                """);
            jdbc.update("INSERT INTO briefing_personal_preferences(id,member_id,revision,choice,created_at,effective_from) VALUES('old-pref','upgrade-owner',7,'{\"companyIds\":[\"brf-test-company\"]}',now(),now()+interval '1 minute')");
            jdbc.update("""
                INSERT INTO briefing_personal_deliveries(id,member_id,round_id,preference_id,mode,scheduled_at,selection_snapshot,selection_sha256,result_snapshot,result_sha256,status,finished_at)
                VALUES('old-delivery','upgrade-owner','brf-test-2026-10-15-morning','old-pref','scheduled',now(),'{}',repeat('a',64),'{}',repeat('b',64),'ready',now())
                """);
            jdbc.update("INSERT INTO briefing_feedback(id,member_id,feature,target_id,target_version,round_id,value,created_at,updated_at) VALUES('old-feedback','upgrade-owner','briefing_round','brf-test-2026-10-15-morning','saved','brf-test-2026-10-15-morning','up',now(),now())");
            var tables=List.of("members","briefing_rounds","briefing_personal_deliveries","briefing_feedback");
            var before=tables.stream().map(t->rows(jdbc,t,false)).toList();String pref=rows(jdbc,"briefing_personal_preferences",false);
            var upgrade=Flyway.configure().dataSource(source).schemas(schema).defaultSchema(schema).outOfOrder(false).load();
            assertEquals(1,upgrade.migrate().migrationsExecuted);upgrade.validate();
            assertEquals(before,tables.stream().map(t->rows(jdbc,t,false)).toList());assertEquals(pref,rows(jdbc,"briefing_personal_preferences",true));
            assertEquals("scheduled",jdbc.queryForObject("SELECT scope FROM briefing_personal_preferences WHERE id='old-pref'",String.class));
            jdbc.update("INSERT INTO briefing_personal_preferences(id,member_id,scope,revision,choice,created_at,effective_from) VALUES('demo-pref','upgrade-owner','demo',7,'{}',now(),now()+interval '1 minute')");
            assertThrows(DataAccessException.class,()->jdbc.update("""
                INSERT INTO briefing_personal_deliveries(id,member_id,round_id,preference_id,mode,scheduled_at,selection_snapshot,selection_sha256,status)
                VALUES('bad-scheduled','upgrade-owner','brf-test-2026-10-15-evening','demo-pref','scheduled',now(),'{}',repeat('c',64),'generating')
                """));
            assertEquals(0,upgrade.migrate().migrationsExecuted);
            assertEquals(before,tables.stream().map(t->rows(jdbc,t,false)).toList());
        } finally {jdbc.execute("DROP SCHEMA IF EXISTS "+schema+" CASCADE");}
    }
    private String rows(JdbcTemplate jdbc,String table,boolean removeScope) {
        return jdbc.queryForObject("SELECT coalesce(jsonb_agg(row ORDER BY row::text),'[]'::jsonb)::text FROM (SELECT to_jsonb(t)"+(removeScope?"-'scope'":"")+" AS row FROM "+table+" t) records",String.class);
    }
}
