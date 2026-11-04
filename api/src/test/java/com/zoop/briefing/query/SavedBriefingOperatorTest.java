package com.zoop.briefing.query;

import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import java.nio.file.*;
import java.nio.file.attribute.PosixFilePermissions;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.DefaultApplicationArguments;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.boot.test.context.runner.WebApplicationContextRunner;
import org.springframework.context.ConfigurableApplicationContext;
import tools.jackson.databind.node.ObjectNode;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

/** Offline/operator boundaries: no HTTP publication route, SQL execution or model transport. */
class SavedBriefingOperatorTest {
    @TempDir Path temporary;

    private Path root() throws Exception {
        Path root=temporary.toRealPath();Files.setPosixFilePermissions(root,PosixFilePermissions.fromString("rwx------"));return root;
    }
    private void write(Path file,byte[] content)throws Exception {
        Files.write(file,content);Files.setPosixFilePermissions(file,PosixFilePermissions.fromString("rw-------"));
    }
    private String bundle(Path root)throws Exception {
        Path tables=Files.createDirectory(root.resolve("tables"));Files.setPosixFilePermissions(tables,PosixFilePermissions.fromString("rwx------"));
        ObjectNode manifest=StrictJson.newObject().put("publicationReady",false).put("noAutomaticPublish",true);
        manifest.putObject("finalization").put("schemaVersion","briefing-finalization-v1");var files=manifest.putObject("files");
        for(String table:SavedBriefingBundle.TABLES) {
            byte[] raw="{}\n".getBytes(java.nio.charset.StandardCharsets.UTF_8);String name="tables/"+table+".jsonl";write(root.resolve(name),raw);
            files.putObject(name).put("sha256",Canonical.sha256(raw)).put("bytes",raw.length);
        }
        byte[] archive="retained original".getBytes(java.nio.charset.StandardCharsets.UTF_8);write(root.resolve("original.json"),archive);
        files.putObject("original.json").put("sha256",Canonical.sha256(archive)).put("bytes",archive.length);
        byte[] raw=Canonical.bytes(manifest);write(root.resolve("manifest.json"),raw);return Canonical.sha256(raw);
    }
    @Test void verifiesAllFilesIncludingArchiveAndNeverReadsChangedManifest()throws Exception {
        Path root=root();String digest=bundle(root);assertEquals(9,SavedBriefingBundle.read(root,digest).tables().size());
        Files.writeString(root.resolve("original.json"),"changed");assertThrows(IllegalArgumentException.class,()->SavedBriefingBundle.read(root,digest));
        assertThrows(IllegalArgumentException.class,()->SavedBriefingBundle.read(root,"f".repeat(64)));
    }
    @Test void rejectsWorldReadableFilesAndSymlinkParents()throws Exception {
        Path root=root();String digest=bundle(root);Path table=root.resolve("tables/companies.jsonl");
        Files.setPosixFilePermissions(table,PosixFilePermissions.fromString("rw-r--r--"));
        assertThrows(IllegalArgumentException.class,()->SavedBriefingBundle.read(root,digest));
        Files.setPosixFilePermissions(table,PosixFilePermissions.fromString("rw-------"));
        Files.move(root.resolve("tables"),root.resolve("actual-tables"));Files.createSymbolicLink(root.resolve("tables"),root.resolve("actual-tables"));
        assertThrows(IllegalArgumentException.class,()->SavedBriefingBundle.read(root,digest));
    }
    @Test void operatorIsOffByDefaultAndCannotRunInWebProcess() {
        new ApplicationContextRunner().withUserConfiguration(SavedBriefingPublicationConfiguration.class).run(c->{
            assertNull(c.getStartupFailure());assertFalse(c.containsBean("savedBriefingPublication"));assertFalse(c.containsBean("savedBriefingPublicationShutdown"));
        });
        new WebApplicationContextRunner().withUserConfiguration(SavedBriefingPublicationConfiguration.class)
            .withBean(SavedBriefingPublisher.class,()->mock(SavedBriefingPublisher.class))
            .withPropertyValues("zoop.briefing.saved-publication.enabled=true").run(c->assertNotNull(c.getStartupFailure()));
    }
    @Test void operatorRejectsOtherWritersAndProtectsExistingResultBeforePublication()throws Exception {
        Path root=root();Path input=Files.createDirectory(root.resolve("bundle"));Files.setPosixFilePermissions(input,PosixFilePermissions.fromString("rwx------"));
        String digest=bundle(input);Path result=root.resolve("result.json");write(result,"retained".getBytes());
        var publisher=mock(SavedBriefingPublisher.class);
        var context=new ApplicationContextRunner().withUserConfiguration(SavedBriefingPublicationConfiguration.class)
            .withBean(SavedBriefingPublisher.class,()->publisher).withPropertyValues("zoop.briefing.saved-publication.enabled=true",
                "zoop.briefing.saved-publication.bundle="+input,"zoop.briefing.saved-publication.manifest-sha256="+digest,"zoop.briefing.saved-publication.result="+result);
        context.withPropertyValues("zoop.graph-delivery.install.enabled=true").run(c->assertNotNull(c.getStartupFailure()));
        context.run(c->{assertNull(c.getStartupFailure());assertThrows(FileAlreadyExistsException.class,()->c.getBean(ApplicationRunner.class).run(new DefaultApplicationArguments()));});
        verifyNoInteractions(publisher);assertEquals("retained",Files.readString(result));
    }
    @Test void onlyExplicitOperatorInstallsShutdownAfterAllStartupRunners() {
        var context=mock(ConfigurableApplicationContext.class);var event=mock(ApplicationReadyEvent.class);when(event.getApplicationContext()).thenReturn(context);
        var shutdown=new SavedBriefingPublicationConfiguration().savedBriefingPublicationShutdown();verifyNoInteractions(context);
        shutdown.onApplicationEvent(event);verify(context).close();
    }
}
