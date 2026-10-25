package com.zoop.admin.jobs;

import static org.junit.jupiter.api.Assertions.*;

import java.util.UUID;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

/** An actual forward upgrade from the published jobs/review schema, not an empty-database-only check. */
@Tag("auth-postgres")
@EnabledIfEnvironmentVariable(named="DB_URL",matches="jdbc:postgresql:.*")
class AnalyzePlanMigrationPostgresTest {
    @Test
    void upgradePreservesLegacyCommandsCheckpointsReviewRowsAndProjectionOwnership() {
        String schema="analyze_upgrade_"+UUID.randomUUID().toString().replace("-","");
        String url=System.getenv("DB_URL");
        var root=new DriverManagerDataSource(url,System.getenv("DB_USERNAME"),System.getenv("DB_PASSWORD"));
        var owner=new JdbcTemplate(root);
        String extensions=owner.queryForObject("SELECT string_agg(DISTINCT n.nspname,',') FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace",String.class);
        String isolated=url+(url.contains("?")?"&":"?")+"currentSchema="+schema+",public"+(extensions==null?"":","+extensions);
        var dataSource=new DriverManagerDataSource(isolated,System.getenv("DB_USERNAME"),System.getenv("DB_PASSWORD"));
        var db=new JdbcTemplate(dataSource);
        try {
            Flyway.configure().dataSource(dataSource).schemas(schema).defaultSchema(schema).target("20261024120000").load().migrate();
            db.update("""
                    INSERT INTO analysis_jobs(id,kind,scope,label,status,reason,requested_by,requested_at,command_key,input,checkpoint,attempts)
                    VALUES('job-legacy01','ingest','admin','기존 수집','queued','합성 이력','admin-history',clock_timestamp(),
                    'legacy-upgrade','{"sourceId":"legacy"}','{"aiUnits":[{"unitKey":"old-unit","aiJobId":"old-ai"}]}','[]')
                    """);
            db.update("""
                    INSERT INTO analysis_jobs(id,kind,scope,label,status,reason,requested_by,requested_at,command_key,input)
                    VALUES('job-internal1','project','internal_projection','기존 투영','queued','합성 이력','system',clock_timestamp(),
                    'internal-upgrade','{}')
                    """);
            db.update("""
                    INSERT INTO review_targets(id,target_type,source_job_id,external_id,source_version,candidate_id,status,source_revision,updated_at)
                    VALUES('legacy-target','candidate','legacy-s3','candidate-1',repeat('a',64),'candidate-1','HOLD','7',clock_timestamp())
                    """);
            String beforeJobs=db.queryForObject("SELECT jsonb_agg(to_jsonb(j) ORDER BY id)::text FROM analysis_jobs j",String.class);
            String beforeReview=db.queryForObject("SELECT jsonb_agg(to_jsonb(t) ORDER BY id)::text FROM review_targets t",String.class);
            Flyway upgrade=Flyway.configure().dataSource(dataSource).schemas(schema).defaultSchema(schema).load();
            assertEquals(1,upgrade.migrate().migrationsExecuted);
            assertEquals(beforeJobs,db.queryForObject("SELECT jsonb_agg(to_jsonb(j)-'plan_id' ORDER BY id)::text FROM analysis_jobs j",String.class));
            assertEquals(beforeReview,db.queryForObject("SELECT jsonb_agg(to_jsonb(t) ORDER BY id)::text FROM review_targets t",String.class));
            assertEquals(0,upgrade.migrate().migrationsExecuted);
            assertEquals(0,db.queryForObject("SELECT count(*) FROM analysis_plans",Integer.class));
            assertEquals(0,db.queryForObject("SELECT count(*) FROM analysis_plan_units",Integer.class));
            assertThrows(DataAccessException.class,()->db.update("""
                    INSERT INTO analysis_jobs(id,kind,scope,label,status,reason,requested_by,requested_at,command_key,input)
                    VALUES('job-invalid1','analyze_plan','internal_projection','잘못된 투영','queued','시험','system',clock_timestamp(),'bad-scope','{}')
                    """));
            assertEquals("project",db.queryForObject("SELECT kind FROM analysis_jobs WHERE id='job-internal1'",String.class));
        } finally {
            owner.execute("DROP SCHEMA IF EXISTS "+schema+" CASCADE");
        }
    }
}
