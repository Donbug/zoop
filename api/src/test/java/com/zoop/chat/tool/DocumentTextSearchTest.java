package com.zoop.chat.tool;

import com.zoop.document.evidence.service.EvidenceArtifactReader;
import com.zoop.document.repository.ArticleRow;
import com.zoop.document.repository.ArtifactRow;
import com.zoop.document.repository.DocumentRegistryRepository;
import com.zoop.document.repository.VersionRow;
import java.time.Instant;
import java.util.Optional;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

class DocumentTextSearchTest {
    private static final Instant NOW = Instant.parse("2026-10-31T00:00:00Z");

    @Test
    void searchesTheVerifiedUtf8BodyOfTheExactVersion() {
        byte[] body = "일반 머리말\n차세대 HBM 공급 계약을 체결했다.".getBytes(java.nio.charset.StandardCharsets.UTF_8);
        ArtifactRow artifact = new ArtifactRow("text-v1", "extracted_text", "artifact-root:extracted_text/text-v1.txt",
                "a".repeat(64), body.length,
                "text/plain; charset=utf-8", NOW);
        VersionRow version = new VersionRow("art-1", "v1", "반도체 업계", "합성 언론사", null, NOW, null,
                "datetime", null, artifact.id(), NOW);
        DocumentTextSearch search = new DocumentTextSearch(registry(version, artifact), row -> body);

        assertTrue(search.matches("art-1", "v1", version.title(), "HBM 계약 소식 알려줘"));
        assertFalse(search.matches("art-1", "v1", version.title(), "배터리 수주 소식 알려줘"));
        assertTrue(search.matches("art-1", "v1", version.title(), "반도체 동향"), "a title match needs no invented excerpt");
    }

    @Test
    void aMeaningfulSearchFailsClosedWhenTheTextStoreIsUnavailable() {
        ArtifactRow artifact = new ArtifactRow("text-v1", "extracted_text", "artifact-root:extracted_text/a.txt",
                "a".repeat(64), 1, "text/plain", NOW);
        VersionRow version = new VersionRow("art-1", "v1", "다른 제목", null, null, NOW, null, "datetime", null,
                artifact.id(), NOW);
        DocumentTextSearch search = new DocumentTextSearch(registry(version, artifact), new EvidenceArtifactReader(null));

        assertThrows(ChatToolUnavailable.class,
                () -> search.matches("art-1", "v1", version.title(), "HBM 계약"));
    }

    @Test
    void termExtractionDropsGenericWordingNumbersAndKoreanParticles() {
        assertEquals(java.util.List.of("hbm", "공급", "계약"),
                DocumentTextSearch.terms("최근 HBM 공급에 대한 계약 소식 2026 알려줘"));
        assertTrue(DocumentTextSearch.terms("최근 소식 알려줘").isEmpty());
    }

    private static DocumentRegistryRepository registry(VersionRow version, ArtifactRow artifact) {
        return new DocumentRegistryRepository() {
            @Override public Optional<VersionRow> findVersion(String articleId, String id) {
                return version.articleId().equals(articleId) && version.version().equals(id) ? Optional.of(version)
                        : Optional.empty();
            }
            @Override public Optional<ArtifactRow> findArtifact(String id) {
                return artifact.id().equals(id) ? Optional.of(artifact) : Optional.empty();
            }
            @Override public boolean insertArticleIfAbsent(String id, String kind, String provider, Instant createdAt) {
                throw new UnsupportedOperationException();
            }
            @Override public Optional<ArticleRow> findArticle(String id) { return Optional.empty(); }
            @Override public Optional<ArticleRow> lockArticle(String id) { return Optional.empty(); }
            @Override public boolean insertArtifactIfAbsent(ArtifactRow row) { throw new UnsupportedOperationException(); }
            @Override public boolean insertVersionIfAbsent(VersionRow row) { throw new UnsupportedOperationException(); }
            @Override public boolean movePointer(String articleId, String expected, String target) {
                throw new UnsupportedOperationException();
            }
        };
    }
}
