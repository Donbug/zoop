package com.zoop.briefing.query;

import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import tools.jackson.databind.JsonNode;

/** Bounded, hash-verified private bundle loader. This never executes a SQL file. */
public record SavedBriefingBundle(JsonNode manifest,String manifestSha256,Map<String,List<JsonNode>> tables) {
    static final Set<String> TABLES=Set.of("companies","artifacts","articles","article_versions","evidence",
        "briefing_rounds","briefing_personal_pools","briefing_personal_preferences","briefing_personal_deliveries");
    public static SavedBriefingBundle read(Path root,String expectedManifestSha256) {
        try {
            if(!root.isAbsolute()||!root.equals(root.toRealPath())||Files.getPosixFilePermissions(root).stream()
                    .anyMatch(p->p.name().startsWith("GROUP_")||p.name().startsWith("OTHERS_")))throw new IllegalArgumentException("absolute_private_bundle_required");
            byte[] bytes=regular(root.resolve("manifest.json"),1_000_000);
            String digest=Canonical.sha256(bytes);
            if(!digest.equals(expectedManifestSha256))throw new IllegalArgumentException("manifest_changed");
            var manifest=StrictJson.parseObject(bytes);
            if(manifest.bool("publicationReady")||!manifest.bool("noAutomaticPublish")||!manifest.has("finalization"))
                throw new IllegalArgumentException("bound_unpublished_bundle_required");
            var files=manifest.object("files");Map<String,List<JsonNode>> tables=new LinkedHashMap<>();
            Map<String,byte[]> verified=new LinkedHashMap<>();long total=0;
            for(String name:files.node().propertyNames()) {
                Path relative=Path.of(name);
                if(relative.isAbsolute()||!relative.equals(relative.normalize())||relative.startsWith(".."))throw new IllegalArgumentException("unsafe_bundle_path");
                Path target=root.resolve(relative);
                if(!target.equals(target.toRealPath()))throw new IllegalArgumentException("private_regular_file_required");
                var expected=files.object(name);byte[] raw=regular(target,32_000_000);total+=raw.length;
                if(total>128_000_000)throw new IllegalArgumentException("bundle_too_large");
                if(!Canonical.sha256(raw).equals(expected.string("sha256"))||raw.length!=expected.count("bytes"))throw new IllegalArgumentException("bundle_integrity_changed");
                if(name.startsWith("tables/"))verified.put(name,raw);
            }
            for(String table:TABLES) {
                String name="tables/"+table+".jsonl";byte[] raw=verified.get(name);
                if(raw==null)throw new IllegalArgumentException("required_table_missing");
                List<JsonNode> rows=new ArrayList<>();
                for(String line:new String(raw,java.nio.charset.StandardCharsets.UTF_8).split("\\R"))if(!line.isBlank())rows.add(StrictJson.parseObject(line).node());
                tables.put(table,List.copyOf(rows));
            }
            return new SavedBriefingBundle(manifest.node(),digest,Map.copyOf(tables));
        }catch(IOException error){throw new IllegalArgumentException("bundle_unavailable");}
    }
    private static byte[] regular(Path path,int limit) throws IOException {
        if(Files.isSymbolicLink(path)||Files.isSymbolicLink(path.getParent())||!Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS)
                ||!Files.getOwner(path).equals(Files.getOwner(path.getParent())))throw new IllegalArgumentException("private_regular_file_required");
        if(Files.getPosixFilePermissions(path).stream().anyMatch(p->p.name().startsWith("GROUP_")||p.name().startsWith("OTHERS_")))
            throw new IllegalArgumentException("private_file_permissions_required");
        try(var in=Files.newInputStream(path)){byte[] raw=in.readNBytes(limit+1);if(raw.length>limit)throw new IllegalArgumentException("bundle_too_large");return raw;}
    }
}
