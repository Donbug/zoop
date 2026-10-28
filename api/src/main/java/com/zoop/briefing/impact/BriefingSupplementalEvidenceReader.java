package com.zoop.briefing.impact;

import com.zoop.briefing.impact.BriefingImpacts.*;
import com.zoop.common.json.Canonical;
import tools.jackson.databind.JsonNode;
import java.net.URI;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.time.*;
import java.util.*;

/** Reads only reviewed local supplements in the SHA-pinned review bundle.
 * Caller has checked the same round/item's current permissions; these never become verified effects. */
final class BriefingSupplementalEvidenceReader {
    static ResearchSupplement read(JsonNode node, JsonNode basis, Instant cutoff, Path directory,
            String company, Clock clock) throws Exception {
        if(node.isNull()||node.isMissingNode()) return null;
        check(directory!=null && company!=null);
        check(text(node,"status").equals("editorial_sources_not_ai_evaluated") && !node.has("label") && !node.has("effect"));
        check(text(node,"roundId").equals(text(basis,"roundId")) && text(node,"eventId").equals(text(basis,"eventId"))
                && text(node,"companyId").equals(company));
        Instant linked=Instant.parse(text(node,"linkedAt"));check(linked.isAfter(cutoff) && !linked.isAfter(clock.instant().plusSeconds(60)));
        check(node.path("sources").isArray() && node.path("sources").size()<=4);
        List<LinkedSource> sources=new ArrayList<>();Set<String> ids=new HashSet<>();
        for(var source:node.path("sources")) {
            check(ids.add(text(source,"id")) && text(source,"companyId").equals(company));
            check(!source.has("label") && !source.has("effect") && source.path("historicalVersionVerified").isBoolean()
                    && !source.path("historicalVersionVerified").asBoolean());
            Instant published=Instant.parse(text(source,"publishedAt"));check(!published.isAfter(cutoff));
            if(source.hasNonNull("modifiedAt"))check(!Instant.parse(text(source,"modifiedAt")).isAfter(cutoff));
            String url=text(source,"url");official(url);
            String transport=text(source,"transport"),timeBasis=text(source,"timeBasis");
            check(Set.of("direct_http","web_tool_extract").contains(transport));
            check(Set.of("issuer_html_jsonld","SEC_index_accepted_America_New_York").contains(timeBasis));
            String sha=text(source,"textSha256");check(sha.matches("[a-f0-9]{64}"));
            byte[] bytes=readFile(directory,text(source,"textPath"));check(Canonical.sha256(bytes).equals(sha));
            String body=StandardCharsets.UTF_8.newDecoder().decode(ByteBuffer.wrap(bytes)).toString();
            String excerpt=text(source,"excerpt");int start=source.path("start").asInt(-1),end=source.path("end").asInt(-1);
            check(source.path("start").isIntegralNumber() && source.path("end").isIntegralNumber()
                    && start>=0 && end>start && end-start<=1000 && end<=body.codePointCount(0,body.length())
                    && excerpt.codePointCount(0,excerpt.length())==end-start
                    && body.substring(body.offsetByCodePoints(0,start),body.offsetByCodePoints(0,end)).equals(excerpt));
            var proof=source.path("timeProof");byte[] timeBytes=readFile(directory,text(proof,"path"));
            check(Canonical.sha256(timeBytes).equals(text(proof,"sha256"))
                    && new String(timeBytes,StandardCharsets.UTF_8).contains(text(proof,"contains")));
            sources.add(new LinkedSource(text(source,"id"),company,text(source,"title"),url,published,timeBasis,
                    text(source,"summary"),text(source,"limitations"),excerpt,transport,sha,false));
        }
        PublicationTimeCheck timeCheck=null;
        if(node.hasNonNull("timeCheck")) {
            var t=node.path("timeCheck");check(text(t,"status").equals("publisher_time_disagreement"));
            String storedUrl=text(t,"storedUrl"),distributionUrl=text(t,"distributionUrl");official(distributionUrl);
            boolean bound=false;for(var e:basis.path("evidence"))if(storedUrl.equals(e.path("url").asString())
                    && Instant.parse(text(t,"storedPublishedAt")).equals(Instant.parse(text(e,"publishedAt"))))bound=true;
            check(bound);
            timeCheck=new PublicationTimeCheck("publisher_time_disagreement",text(t,"summary"),text(t,"limitation"),
                    Instant.parse(text(t,"storedPublishedAt")),Instant.parse(text(t,"distributionPublishedAt")),storedUrl,distributionUrl);
        }
        check(!sources.isEmpty()||timeCheck!=null);
        return new ResearchSupplement("editorial_sources_not_ai_evaluated",linked,List.copyOf(sources),timeCheck);
    }
    private static void official(String url) {
        URI u=URI.create(url);check("https".equals(u.getScheme()) && u.getUserInfo()==null
                && u.getPort()==-1 && Set.of("news.samsung.com","www.sec.gov","www.globenewswire.com").contains(u.getHost()));
    }
    private static byte[] readFile(Path root,String relative) throws Exception {
        Path name=Path.of(relative);check(relative.startsWith("supplements/") && !name.isAbsolute()
                && name.normalize().equals(name) && !relative.contains(".."));
        Path path=root.resolve(name).normalize();check(path.startsWith(root));
        for(Path p=path;p!=null;p=p.getParent())check(!Files.isSymbolicLink(p));
        check(Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS) && Files.size(path)<=2_000_000);
        byte[] bytes=Files.readAllBytes(path);check(bytes.length<=2_000_000);return bytes;
    }
    private static String text(JsonNode n,String f) {check(n.path(f).isString()&&!n.path(f).asString().isBlank()
            &&n.path(f).asString().length()<=4000);return n.path(f).asString();}
    private static void check(boolean ok){if(!ok)throw new IllegalArgumentException("invalid_supplemental_evidence");}
}
