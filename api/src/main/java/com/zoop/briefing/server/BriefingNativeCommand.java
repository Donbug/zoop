package com.zoop.briefing.server;

import com.zoop.admin.auth.repository.JdbcAdminAuditRepository;
import com.zoop.admin.graph.AdminGraphVersionService;
import com.zoop.admin.graph.JdbcAdminGraphVersionRepository;
import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import com.zoop.document.analysis.repository.JdbcDocumentAnalysisRepository;
import com.zoop.document.evidence.repository.JdbcEvidenceReadRepository;
import com.zoop.document.evidence.service.*;
import com.zoop.document.importer.*;
import com.zoop.document.repository.JdbcDocumentRegistryRepository;
import com.zoop.document.service.*;
import com.zoop.graph.exclusion.*;
import com.zoop.graph.read.JdbcDisclosureExclusionReader;
import com.zoop.graph.importer.*;
import com.zoop.graph.publication.*;
import com.zoop.graph.snapshot.*;
import com.zoop.graph.version.JdbcGraphVersionRepository;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.*;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.node.ObjectNode;

/** Private CLI: existing native import/composition/activation services with CAS and current-source checks. No Spring startup. */
public final class BriefingNativeCommand {
    private final Clock clock=Clock.systemUTC();
    private final NamedParameterJdbcTemplate jdbc;
    private final TransactionTemplate tx;
    private final JdbcDocumentRegistryRepository registry;
    private final JdbcGraphHandoffRepository graph;
    private final JdbcGraphVersionRepository versions;
    private final JdbcGraphPublicationRepository publications;
    private final ArtifactFileStore files;
    private final DocumentReadSources sources;
    private final JdbcDisclosureExclusionReader exclusions;
    private final GraphPublicationReader reader;
    private final GraphPublicationAuthority authority;
    private final Path work;
    private final Path grantPath,authorityRoot;
    private final boolean additiveAllowed;
    private final String authorizationRef;

    public BriefingNativeCommand(Map<String,String> env) {
        var db=new DriverManagerDataSource(required(env,"DB_URL"),required(env,"DB_USERNAME"),required(env,"DB_PASSWORD"));
        jdbc=new NamedParameterJdbcTemplate(db);tx=new TransactionTemplate(new DataSourceTransactionManager(db));tx.setTimeout(120);
        registry=new JdbcDocumentRegistryRepository(jdbc);graph=new JdbcGraphHandoffRepository(jdbc,new JdbcDocumentAnalysisRepository(jdbc));
        versions=new JdbcGraphVersionRepository(jdbc,clock);publications=new JdbcGraphPublicationRepository(jdbc);
        files=ArtifactFileStore.at(Path.of(required(env,"BRIEFING_USAGE_ARTIFACT_ROOT")));
        sources=new DocumentReadSources(Path.of(required(env,"ZOOP_DOCUMENT_READ_INGESTION_SOURCES")));
        exclusions=new JdbcDisclosureExclusionReader(jdbc);
        reader=new GraphPublicationReader(graph,registry,files,publications);authority=new GraphPublicationAuthority(registry,sources,exclusions,clock);
        work=Path.of(required(env,"BRIEFING_SERVER_WORK_ROOT")).toAbsolutePath().normalize();
        grantPath=Path.of(required(env,"ZOOP_DOCUMENT_READ_GRANTS"));
        authorityRoot=Path.of(required(env,"BRIEFING_SERVER_AUTHORITY_ROOT"));
        additiveAllowed="true".equals(env.get("BRIEFING_SERVER_ADDITIVE_GRAPH_ALLOWED"));authorizationRef=env.get("BRIEFING_SERVER_AUTHORIZATION_REF");
    }

    public static void main(String[] args) {
        try {
            if(args.length!=2||!Set.of("state","import","activate").contains(args[0]))throw new IllegalArgumentException();
            var command=new BriefingNativeCommand(System.getenv());var path=command.owned(Path.of(args[1]));
            var request=StrictJson.parseObject(Files.readAllBytes(path));
            var result=switch(args[0]) {case "state"->command.state();case "import"->command.importNative(request);case "activate"->command.activate(request);default->throw new IllegalArgumentException();};
            System.out.println("BRIEFING_SERVER_RESULT="+new String(StrictJson.write(result),java.nio.charset.StandardCharsets.UTF_8));
        } catch(Exception failure) {System.err.println("BRIEFING_NATIVE_FAILED="+failure.getClass().getSimpleName());System.exit(1);}
    }

    private Path owned(Path path) throws java.io.IOException {
        path=path.toAbsolutePath().normalize();if(!path.startsWith(work)||Files.isSymbolicLink(path)||!path.toRealPath().startsWith(work.toRealPath())||Files.size(path)>4*1024*1024)throw new IllegalArgumentException("private_path");return path;
    }

    public ObjectNode state() {
        var active=versions.active().orElseThrow();
        if(!"snapshot".equals(active.kind()))throw new IllegalArgumentException("existing_native_publication_required");
        var publication=reader.read(active.id());authority.requireFullRights(publication,"briefing-native-baseline");
        var state=graph.publicationState();
        return StrictJson.newObject().put("graphVersion",active.id()).put("receiptSha256",publication.receipt().sha256())
                .put("reviewRevision",state.reviewRevision()).put("ruleRevision",state.ruleRevision()).put("checkedAt",clock.instant().toString());
    }

    public ObjectNode importNative(StrictJson.Obj request) throws Exception {
        Path root=owned(Path.of(request.string("root")).resolve("ready.json")).getParent();
        Path ingestion=Path.of(request.string("ingestionState"));Path source=Path.of(request.string("sourceFile")).toRealPath();
        if(!source.startsWith(authorityRoot.toRealPath())||Files.isSymbolicLink(source)||Files.size(source)>2_000_000)throw new IllegalArgumentException("authority_namespace");
        if(!ingestion.toRealPath().startsWith(root.toRealPath()))throw new IllegalArgumentException("native_namespace");
        var exporter=ProcessIngestionExporter.forPaths(Path.of("/usr/local/bin/zoop-ai-ingest"),ingestion,source);
        var parser=new IngestionExportParser();
        var observation=request.object("observation");
        var selector=new Observation(observation.string("roundId"),observation.string("sourceId"),observation.count("page"),observation.count("ordinal"),
                observation.string("documentId"),observation.string("rawVersion"),observation.string("documentVersion"));
        var service=new DocumentRegistrationService(registry,clock) {
            @Override public RegistrationOutcome register(RegistrationCommand command) {return tx.execute(status->super.register(command));}
        };
        var imported=new DocumentImporter(exporter,parser,files,service).run(new ImportRequest(List.of(new ImportItem(ArticleKind.NEWS,selector,PointerPolicy.keep()))));
        if(!imported.succeeded())throw new IllegalStateException("native_document_"+imported.firstFailure());
        var argv=List.of("/usr/local/bin/zoop-ai-handoff","export","--state-dir",root.resolve("handoff").toString(),
                "--relation-state-dir",root.resolve("s3").toString(),"--extraction-state-dir",root.resolve("s2").toString(),
                "--ingestion-state-dir",ingestion.toString(),"--sources",source.toString(),"--canonical",root.resolve("canonical.json").toString(),
                "--decisions",root.resolve("decisions.json").toString(),"--bindings",root.resolve("bindings.json").toString());
        var handoff=new ProcessHandoffExporter(argv,Duration.ofSeconds(90),ProcessHandoffExporter.MAX_STDOUT_BYTES,System.getenv(),"/tmp");
        var manifest=request.object("manifest");var receipt=request.object("handoffReceipt");
        var pin=new GraphHandoffRequest(manifest.string("handoffId"),receipt.string("manifestDigest"),receipt.string("bundleDigest"),"briefing-live-intake-v1");
        var result=new GraphHandoffImporter(handoff,exporter,parser,files,registry,graph,tx,clock).run(pin);
        if(!result.succeeded())throw new IllegalStateException("native_graph_import_refused");
        String version=GraphHandoffImporter.versionId(pin.handoffId());
        return StrictJson.newObject().put("sourceVersion",version).put("receiptSha256",registry.findArtifact("artifact-receipt-"+version).orElseThrow().sha256());
    }

    public ObjectNode activate(StrictJson.Obj request) {
        var baseline=request.object("baseline");var incoming=request.object("incoming");
        byte[] decisions=Canonical.bytes(PublicationMerger.emptyDecisions().node());
        var composition=new PublicationComposeRequest(baseline.string("graphVersion"),List.of(incoming.string("sourceVersion")),baseline.string("graphVersion"),
                baseline.string("receiptSha256"),Map.of(incoming.string("sourceVersion"),incoming.string("receiptSha256")),
                baseline.count("ruleRevision"),baseline.count("reviewRevision"),Canonical.sha256(decisions),"briefing-live-additive-v1");
        var composer=new GraphPublicationComposer(files,graph,registry,versions,publications,reader,authority,sources,tx,clock);
        var result=composer.run(composition,decisions);if(!"succeeded".equals(result.path("status").asString()))throw new IllegalStateException("native_compose_not_current");
        String version=result.path("graphVersionId").asString();
        var snapshots=new ArtifactGraphSnapshotStore(files,registry,new FixtureGraphSnapshotStore(getClass().getClassLoader()));
        var evidence=new EvidenceService(new JdbcEvidenceReadRepository(jdbc),registry,
                new DocumentReadGrants(grantPath),sources,
                (v,at,id)->{throw new IllegalStateException("activation_command_has_no_public_read");},new EvidenceArtifactReader(files),clock,tx,reader);
        var activationService=new AdminGraphVersionService(new JdbcAdminGraphVersionRepository(jdbc),versions,snapshots,exclusions,
                new DisclosureExclusionCarry(new JdbcDisclosureExclusionRepository(jdbc)),evidence,reader,authority,new JdbcAdminAuditRepository(jdbc),
                new tools.jackson.databind.ObjectMapper(),clock,false,"artifact");
        return tx.execute(status->{
            // Do not adopt a pointer changed after the source set was admitted.
            if(!versions.active().map(v->v.id().equals(baseline.string("graphVersion"))).orElse(false))throw new IllegalStateException("concurrent_activation");
            if(!additiveAllowed)throw new IllegalStateException("additive_graph_opt_in_required");
            var activated=activationService.activateBriefingAddition(version,baseline.string("graphVersion"),
                    authorizationRef,"briefing-native-activate");
            return StrictJson.newObject().put("graphVersion",version).put("previousGraphVersion",activated.previousVersionId())
                    .put("activatedAt",activated.activatedAt().toString());
        });
    }
    private static String required(Map<String,String> env,String name){var v=env.get(name);if(v==null||v.isBlank())throw new IllegalArgumentException(name);return v;}
}
