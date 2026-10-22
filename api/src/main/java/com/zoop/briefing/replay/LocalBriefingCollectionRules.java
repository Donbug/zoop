package com.zoop.briefing.replay;

import com.zoop.common.json.StrictJson;
import java.time.*;
import java.util.Map;
import tools.jackson.databind.JsonNode;

/** Single manual local round. Never authorizes an operational publication or a historical backfill. */
final class LocalBriefingCollectionRules {
    static final String MODE = "local_collection_validation";
    private static final ZoneId KST = ZoneId.of("Asia/Seoul");

    static boolean enabled(StrictJson.Obj bundle) {
        return MODE.equals(bundle.string("mode"));
    }

    static void metadata(StrictJson.Obj bundle) {
        var local = bundle.object("localCollection");
        require("zoop-local-collection-v1".equals(local.string("schemaVersion")) && local.bool("manualValidation")
                && local.bool("collectedBeforeCutoff") && !local.bool("productionAuthorized")
                && bundle.string("sourceFileSha256").equals(local.string("sourceFileSha256"))
                && local.string("collectionPlanSha256").matches("[0-9a-f]{64}")
                && local.node().equals(bundle.object("authorization").object("localCollection").node()),
                "metadata");
    }

    static void window(StrictJson.Obj bundle, StrictJson.Obj round, Map<String, JsonNode> sources,
            PublicationClockRegistry clocks) {
        var window = round.object("window");
        Instant start = Instant.parse(window.string("from")), end = Instant.parse(window.string("to"));
        Instant discovery = Instant.parse(bundle.object("localCollection").string("discoveryTo"));
        require(!window.bool("openStart") && start.isBefore(discovery) && !discovery.isAfter(end)
                && Duration.between(start, end).compareTo(Duration.ofHours(48)) <= 0
                && !end.isAfter(Instant.now())
                && end.atZone(KST).toLocalDate().toString().equals(round.string("date"))
                && java.util.Set.of("morning", "evening").contains(round.string("edition"))
                && round.object("localCollection").node().equals(bundle.object("localCollection").node()),
                "window");
        for (var item : sources.entrySet()) {
            var source = StrictJson.Obj.of(item.getValue());
            var clock = clocks.verified.get(item.getKey());
            require(clock != null, "unverified_clock");
            Instant captured = Instant.parse(source.string("collectedAt"));
            Instant checked = Instant.parse(source.object("capture").string("checkedAt"));
            var capture = source.object("capture");
            require(!clock.publishedAt().isAfter(captured) && !captured.isAfter(end) && !checked.isAfter(end)
                    && captured.equals(checked) && capture.bool("sameResponseBodyAndClock")
                    && capture.string("htmlSha256").equals(clock.htmlSha256())
                    && Instant.parse(capture.string("publishedAt")).equals(clock.publishedAt()), "late_or_unbound_source");
        }
    }

    static void catalogue(StrictJson.Obj round, java.nio.file.Path output, org.springframework.jdbc.core.JdbcTemplate jdbc) {
        var identity = round.object("identity");
        if (!identity.has("publicationCompanyIds")) return;
        try {
            var path = output.resolve("publication-companies.json");
            require(java.nio.file.Files.isRegularFile(path, java.nio.file.LinkOption.NOFOLLOW_LINKS)
                    && java.nio.file.Files.size(path) <= 2_000_000, "catalogue_file");
            byte[] raw = java.nio.file.Files.readAllBytes(path);
            require(com.zoop.common.json.Canonical.sha256(raw).equals(identity.string("publicationCatalogSha256")), "catalogue_hash");
            var ids = StrictJson.parseObject(raw).objects("companies").stream().map(c -> c.string("company_id")).sorted().toList();
            require(ids.equals(identity.strings("publicationCompanyIds")) && java.util.Set.copyOf(ids).size() == ids.size(), "catalogue_population");
            for (String id : ids) require(Integer.valueOf(1).equals(jdbc.queryForObject("SELECT count(*) FROM companies WHERE id=?", Integer.class, id)), "catalogue_not_registered");
        } catch (java.io.IOException error) { throw new IllegalArgumentException("Local publication catalogue unavailable", error); }
    }

    static void identity(StrictJson.Obj bundle, StrictJson.Obj round) {
        var identity = round.object("identity");
        if (identity.has("publicationCompanyIds")) {
            var allowed = java.util.Set.copyOf(identity.strings("publicationCompanyIds"));
            require(!allowed.isEmpty() && identity.string("publicationCatalogSha256").matches("[0-9a-f]{64}"), "publication_catalog");
            for (var selected : round.objects("selected")) for (var link : selected.objects("companyLinks"))
                require(allowed.contains(link.string("companyId")), "company_outside_publication_scope");
        }
        require(identity.object("localCollection").node().equals(bundle.object("localCollection").node())
                && identity.object("baseline").string("from").equals(round.object("window").string("from"))
                && "local_validation_window_start".equals(identity.object("baseline").string("meaning")),
                "identity");
    }

    private static void require(boolean ok, String code) {
        if (!ok) throw new IllegalArgumentException("Local briefing collection rejected: " + code);
    }
}
