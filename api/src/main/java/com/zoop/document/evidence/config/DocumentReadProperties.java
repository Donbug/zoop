package com.zoop.document.evidence.config;

import java.nio.file.Files;
import java.nio.file.InvalidPathException;
import java.nio.file.Path;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * {@code zoop.document-read.*}, normally set from {@code ZOOP_DOCUMENT_READ_GRANTS} and
 * {@code ZOOP_DOCUMENT_READ_ARTIFACT_ROOT} (see {@code application.yml}). Both are optional and independent of the operator
 * import and analysis settings, and neither changes anything on disk. Unset (blank), the web read answers 503 where it needs the
 * value: without {@code grants} every evidence read, without {@code artifactRoot} only the one that has to read an exact
 * receipt file. A set value that is not usable fails startup, naming the setting and not its value.
 *
 * @param grants       the operator's flat S1 grant registry file ({@code zoop-ai-s1-1}), re-read on every request
 * @param artifactRoot the artifact store root, only to read the exact receipt of a cache-served summary (read-only, no lock)
 */
@ConfigurationProperties("zoop.document-read")
public record DocumentReadProperties(String grants, String artifactRoot) {

    /** The registry path, or {@code null} when unset. */
    public Path grantsPath() {
        Path path = path("grants", grants);
        if (path != null && !Files.isRegularFile(path)) {
            throw new DocumentReadConfigurationException("grants", "must be an existing file");
        }
        return path;
    }

    /** The artifact root, or {@code null} when unset. */
    public Path artifactRootPath() {
        Path path = path("artifact-root", artifactRoot);
        if (path != null && !Files.isDirectory(path)) {
            throw new DocumentReadConfigurationException("artifact-root", "must be an existing directory");
        }
        return path;
    }

    private static Path path(String setting, String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        try {
            Path path = Path.of(value);
            if (!path.isAbsolute() || !path.equals(path.normalize())) {
                throw new DocumentReadConfigurationException(setting, "must be a normalized absolute path");
            }
            return path;
        } catch (InvalidPathException error) {
            throw new DocumentReadConfigurationException(setting, "must be a valid path");
        }
    }

    @Override
    public String toString() {
        return "DocumentReadProperties[grants=" + (grants == null || grants.isBlank() ? "unset" : "set") + ", artifactRoot="
                + (artifactRoot == null || artifactRoot.isBlank() ? "unset" : "set") + "]";
    }
}
