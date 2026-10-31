package com.zoop.graph.delivery;

import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import com.zoop.common.json.StrictJson;
import com.zoop.document.repository.ArticleRow;
import com.zoop.document.repository.ArtifactRow;
import com.zoop.document.repository.DocumentRegistryRepository;
import com.zoop.document.repository.VersionRow;
import com.zoop.graph.importer.LegacyRealPackage;
import com.zoop.graph.publication.GraphPublicationReader;
import com.zoop.graph.publication.PublicationException;
import com.zoop.graph.publication.PublicationMerger;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class GraphDeliveryClosureTest {
    private static final Instant NOW = Instant.parse("2026-10-31T00:00:00Z");
    @TempDir Path temporary;

    @Test void hiddenLegacyArticleRequiresExactGrantTupleAndCurrentUrlScope() throws Exception {
        String originalId = "a".repeat(64), articleId = LegacyRealPackage.articleId(originalId);
        String version = "b".repeat(64), hash = "c".repeat(64);
        var text = new ArtifactRow("text", "extracted_text", "artifact-root:extracted_text/text.txt", hash, 12,
                "text/plain; charset=utf-8", NOW);
        var registry = mock(DocumentRegistryRepository.class);
        var article = new ArticleRow(articleId, "news", "legacy-source", null, "available");
        when(registry.lockArticle(articleId)).thenReturn(Optional.of(article));
        when(registry.findArticle(articleId)).thenReturn(Optional.of(article));
        when(registry.findVersion(articleId, version)).thenReturn(Optional.of(new VersionRow(articleId, version,
                "Synthetic legacy", null, "https://allowed.invalid/story", NOW, null, "datetime", null, text.id(), NOW)));
        when(registry.findArtifact(text.id())).thenReturn(Optional.of(text));
        var bundle = StrictJson.newObject().put("schemaVersion", LegacyRealPackage.BUNDLE_SCHEMA);
        var sourceArticle = bundle.putArray("articles").addObject().put("articleId", articleId).put("articleVersion", version)
                .put("originalArticleId", originalId).put("textSha256", hash).put("url", "https://allowed.invalid/story");
        sourceArticle.putObject("grantBinding").put("originalArticleId", originalId).put("originalArticleVersion", version)
                .put("sourceId", "legacy-source").put("grantId", "legacy-grant").put("revision", "1").put("kind", "news");
        var projection = new PublicGraphSnapshot(3, "original", "legacy-real:" + hash, List.of(), List.of(), List.of(),
                List.of(new PublicGraphSnapshot.Article(articleId, version, "Synthetic legacy", "https://allowed.invalid/story", NOW.toString())), List.of());
        var source = new GraphPublicationReader.Contribution("original", "legacy-real:" + hash, "legacy-real", null, null,
                projection, StrictJson.Obj.of(bundle));
        var visible = new PublicGraphSnapshot(3, "publication", "publication:" + hash, List.of(), List.of(), List.of(), List.of(), List.of());
        var publication = new GraphPublicationReader.Publication("publication", "publication:" + hash, hash, null, null,
                null, null, visible, List.of(source), PublicationMerger.emptyDecisions(), Map.of(), Map.of());
        Path authority = temporary.toRealPath().resolve("authority.json");
        writeAuthority(authority, "allowed.invalid", "1");
        var clock = Clock.fixed(NOW, ZoneOffset.UTC);
        assertDoesNotThrow(() -> GraphDeliveryClosure.requireRights(publication, registry,
                GraphDeliveryClosure.currentRegistry(authority.toString()), clock));
        writeAuthority(authority, "different.invalid", "1");
        assertEquals("rights_denied", assertThrows(PublicationException.class, () -> GraphDeliveryClosure.requireRights(
                publication, registry, GraphDeliveryClosure.currentRegistry(authority.toString()), clock)).code());
        writeAuthority(authority, "allowed.invalid", "2");
        assertEquals("rights_denied", assertThrows(PublicationException.class, () -> GraphDeliveryClosure.requireRights(
                publication, registry, GraphDeliveryClosure.currentRegistry(authority.toString()), clock)).code());
    }

    private void writeAuthority(Path path, String host, String revision) throws Exception {
        Files.writeString(path, """
                {"schemaVersion":"zoop-ingestion-s2-1","revision":"registry-a","sources":[{
                  "sourceId":"legacy-source","adapter":"authored-files","inputRoot":"/synthetic",
                  "allowedHosts":["%s"],"scopes":[{"scopeId":"scope-a","selection":"all",
                    "initialCursor":null,"articleXPath":null,"timestampLimitations":["synthetic"]}],
                  "grant":{"grantId":"legacy-grant","revision":"%s","sourceId":"legacy-source","enabled":true,
                    "rights":"known","allowedOperations":["read","store","quote-display"],"recipients":[],
                    "purposes":[],"evidence":["synthetic operator grant"],"expiresAt":null}}]}
                """.formatted(host, revision));
    }
}
