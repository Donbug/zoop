package com.zoop.chat.tool;

import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.artifact.storage.ArtifactStoreException;
import com.zoop.document.evidence.config.DocumentReadProperties;
import com.zoop.document.evidence.service.EvidenceArtifactReader;
import com.zoop.document.repository.ArtifactRow;
import com.zoop.document.repository.DocumentRegistryRepository;
import com.zoop.document.repository.VersionRow;
import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.text.Normalizer;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import org.springframework.dao.DataAccessException;
import org.springframework.stereotype.Component;

/**
 * Bounded lexical index over the immutable extracted text of an exact article version.
 *
 * <p>The registry row and artifact hash/size are checked before text enters the index. Nothing is written and the original
 * body is never returned to the chatbot: this component only answers whether a server-derived set of terms occurs in a
 * title or body. Entries are local to this JVM and evicted by total UTF-8 size, so a search cannot retain an unbounded copy
 * of the artifact store.
 */
@Component
public final class DocumentTextSearch {
    static final long MAX_CACHE_BYTES = 32L * 1024 * 1024;
    static final int MAX_TERMS = 12;

    private static final Set<String> STOP_WORDS = Set.of(
            "관련", "대한", "대해", "문서", "기사", "뉴스", "공시", "소식", "내용", "정보", "최근", "최신",
            "알려줘", "알려주세요", "보여줘", "보여주세요", "찾아줘", "찾아주세요", "검색", "무엇", "뭐야", "어떤",
            "있어", "있나요", "인가요", "어떻게", "그리고", "또는", "오늘", "어제", "그제", "이번", "지난");
    private static final List<String> PARTICLES = List.of(
            "으로부터", "에게서", "에서는", "으로는", "이라는", "라고는", "부터", "까지", "에서", "에게", "한테",
            "으로", "이라고", "라고", "처럼", "보다", "마다", "이나", "거나", "께서", "에도", "에는", "의", "은",
            "는", "이", "가", "을", "를", "와", "과", "도", "만", "로", "에");

    private record Key(String artifactId, String sha256) { }
    private record Indexed(String text, int bytes) { }

    @FunctionalInterface
    interface TextArtifacts {
        byte[] read(ArtifactRow artifact);
    }

    private final DocumentRegistryRepository registry;
    private final TextArtifacts artifacts;
    private final Map<Key, Indexed> cache = new LinkedHashMap<>(16, 0.75f, true);
    private long cachedBytes;

    public DocumentTextSearch(DocumentRegistryRepository registry, DocumentReadProperties properties) {
        this(registry, new EvidenceArtifactReader(properties.artifactRootPath() == null ? null
                : ArtifactFileStore.at(properties.artifactRootPath()))::read);
    }

    DocumentTextSearch(DocumentRegistryRepository registry, EvidenceArtifactReader artifacts) {
        this(registry, artifacts::read);
    }

    DocumentTextSearch(DocumentRegistryRepository registry, TextArtifacts artifacts) {
        this.registry = registry;
        this.artifacts = artifacts;
    }

    /** True when any meaningful server-derived term occurs in the title or verified full body. */
    public boolean matches(String articleId, String versionId, String title, String searchText) {
        List<String> terms = terms(searchText);
        if (terms.isEmpty()) return true;
        String heading = normalize(title == null ? "" : title);
        if (terms.stream().anyMatch(heading::contains)) return true;

        final ArtifactRow artifact;
        try {
            VersionRow version = registry.findVersion(articleId, versionId)
                    .orElseThrow(() -> new ChatToolUnavailable("the searched document version is unavailable"));
            artifact = registry.findArtifact(version.textArtifactId())
                    .filter(row -> "extracted_text".equals(row.kind()))
                    .orElseThrow(() -> new ChatToolUnavailable("the searched document text is unavailable"));
        } catch (DataAccessException unavailable) {
            throw new ChatToolUnavailable("the searched document registry cannot be read", unavailable);
        }
        String body = indexed(artifact);
        return terms.stream().anyMatch(body::contains);
    }

    private String indexed(ArtifactRow artifact) {
        Key key = new Key(artifact.id(), artifact.sha256());
        synchronized (cache) {
            Indexed hit = cache.get(key);
            if (hit != null) return hit.text();
        }

        final byte[] bytes;
        try {
            bytes = artifacts.read(artifact);
        } catch (ArtifactStoreException unavailable) {
            throw new ChatToolUnavailable("the searched document text cannot be read", unavailable);
        }
        String decoded;
        try {
            decoded = StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString();
        } catch (CharacterCodingException invalid) {
            throw new ChatToolUnavailable("the searched document text is not valid UTF-8", invalid);
        }
        Indexed entry = new Indexed(normalize(decoded), bytes.length);
        synchronized (cache) {
            Indexed raced = cache.get(key);
            if (raced != null) return raced.text();
            if (entry.bytes() <= MAX_CACHE_BYTES) {
                cache.put(key, entry);
                cachedBytes += entry.bytes();
                while (cachedBytes > MAX_CACHE_BYTES && !cache.isEmpty()) {
                    var oldest = cache.entrySet().iterator();
                    var removed = oldest.next();
                    cachedBytes -= removed.getValue().bytes();
                    oldest.remove();
                }
            }
        }
        return entry.text();
    }

    static List<String> terms(String value) {
        if (value == null || value.isBlank()) return List.of();
        String normalized = normalize(value);
        Set<String> result = new LinkedHashSet<>();
        for (String raw : normalized.split(" ")) {
            String term = stripParticle(raw);
            if (term.codePointCount(0, term.length()) < 2 || STOP_WORDS.contains(term)
                    || term.codePoints().allMatch(Character::isDigit)) continue;
            result.add(term);
            if (result.size() == MAX_TERMS) break;
        }
        return List.copyOf(result);
    }

    private static String stripParticle(String value) {
        for (String particle : PARTICLES) {
            if (value.endsWith(particle) && value.length() > particle.length()) {
                String stem = value.substring(0, value.length() - particle.length());
                if (stem.codePointCount(0, stem.length()) >= 2) return stem;
            }
        }
        return value;
    }

    private static String normalize(String value) {
        String folded = Normalizer.normalize(value, Normalizer.Form.NFKC).toLowerCase(Locale.ROOT);
        StringBuilder out = new StringBuilder(folded.length());
        boolean space = true;
        for (int offset = 0; offset < folded.length();) {
            int cp = folded.codePointAt(offset);
            offset += Character.charCount(cp);
            if (Character.isLetterOrDigit(cp)) {
                out.appendCodePoint(cp);
                space = false;
            } else if (!space) {
                out.append(' ');
                space = true;
            }
        }
        return out.toString().strip();
    }
}
