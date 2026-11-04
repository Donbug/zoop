package com.zoop.briefing.query;

import com.zoop.common.json.StrictJson;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermissions;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.ApplicationContext;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.ApplicationListener;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.context.WebApplicationContext;

/** Disabled by default; one explicit non-web operator process, never an HTTP publishing endpoint. */
@Configuration(proxyBeanMethods=false)
@ConditionalOnProperty(name="zoop.briefing.saved-publication.enabled",havingValue="true")
public class SavedBriefingPublicationConfiguration {
    @Bean ApplicationRunner savedBriefingPublication(ApplicationContext context,SavedBriefingPublisher publisher) {
        if(context instanceof WebApplicationContext)throw new IllegalArgumentException("saved_publication_requires_non_web_process");
        for(String key:new String[]{"zoop.briefing.personal-scheduler-enabled","zoop.briefing.common-scheduler-enabled",
                "zoop.briefing.selected-generation-enabled","zoop.document-analysis.enabled","zoop.document-import.enabled",
                "zoop.graph-handoff-import.enabled","zoop.disclosure-exclusion.enabled","zoop.document-bindings.enabled",
                "zoop.legacy-real-import.enabled","zoop.graph-publication-compose.enabled","zoop.graph-publication-prepare.enabled",
                "zoop.graph-delivery.seal.enabled","zoop.graph-delivery.install.enabled",
                "zoop.briefing.replay.import-enabled"})
            if(context.getEnvironment().getProperty(key,Boolean.class,false))throw new IllegalArgumentException("saved_publication_requires_other_writers_disabled");
        var env=context.getEnvironment();Path bundle=Path.of(env.getRequiredProperty("zoop.briefing.saved-publication.bundle"));
        String digest=env.getRequiredProperty("zoop.briefing.saved-publication.manifest-sha256");
        Path result=Path.of(env.getRequiredProperty("zoop.briefing.saved-publication.result"));
        if(!result.isAbsolute()||!result.equals(result.normalize())||result.startsWith(bundle))throw new IllegalArgumentException("private_result_path_required");
        try {
            Path parent=result.getParent();
            if(parent==null||!parent.equals(parent.toRealPath())||Files.getPosixFilePermissions(parent).stream()
                    .anyMatch(p->p.name().startsWith("GROUP_")||p.name().startsWith("OTHERS_")))
                throw new IllegalArgumentException("private_result_parent_required");
        }catch(java.io.IOException unavailable){throw new IllegalArgumentException("private_result_parent_required");}
        return args -> {
            // Reserve before the database commit. An interrupted output can be recovered
            // with a new result path; the database import receipt makes retry a no-op.
            try(var out=Files.newByteChannel(result,java.util.Set.of(StandardOpenOption.WRITE,StandardOpenOption.CREATE_NEW,LinkOption.NOFOLLOW_LINKS),
                    PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")))) {
                var saved=SavedBriefingBundle.read(bundle,digest);
                byte[] response=StrictJson.write(publisher.publish(saved.manifest(),saved.manifestSha256(),saved.tables()));
                var bytes=java.nio.ByteBuffer.wrap(response);while(bytes.hasRemaining())out.write(bytes);
            }
        };
    }

    @Bean ApplicationListener<ApplicationReadyEvent> savedBriefingPublicationShutdown() {
        return ready -> ready.getApplicationContext().close();
    }
}
