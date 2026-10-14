package com.zoop.document.importer;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.InvalidPathException;
import java.nio.file.LinkOption;
import java.nio.file.Path;

/**
 * Validated paths of an enabled operator import. Every path is absolute; the request, S2-1 CLI and sources registry are
 * regular files and the CLI is executable; the S2-1 state directory and the artifact root are existing directories that
 * do not contain one another; the artifact root has no symlink component; the result file does not exist yet and its
 * parent does. Nothing here is a secret, but a failure still names only the setting.
 *
 * @param request       operator request JSON
 * @param result        result file, created exclusively by the run
 * @param ingestionCli  the installed {@code zoop-ai-ingest} executable
 * @param ingestionState the S2-1 ledger directory (the CLI opens it read-only)
 * @param ingestionSources the current operator source registry, which is the import authority
 * @param artifactRoot  root of the local artifact file store
 */
public record DocumentImportSettings(Path request, Path result, Path ingestionCli, Path ingestionState,
        Path ingestionSources, Path artifactRoot) {

    public static DocumentImportSettings of(String request, String result, String ingestionCli, String ingestionState,
            String ingestionSources, String artifactRoot) {
        Path requestPath = absolute("request", request);
        Path resultPath = absolute("result", result);
        Path cliPath = absolute("ingestion-cli", ingestionCli);
        Path statePath = absolute("ingestion-state-dir", ingestionState);
        Path sourcesPath = absolute("ingestion-sources", ingestionSources);
        Path rootPath = absolute("artifact-root", artifactRoot);

        require(Files.isRegularFile(requestPath), "request", "must be an existing file");
        require(Files.isRegularFile(cliPath) && Files.isExecutable(cliPath), "ingestion-cli",
                "must be an existing executable file");
        require(Files.isRegularFile(sourcesPath), "ingestion-sources", "must be an existing file");
        require(Files.isDirectory(statePath), "ingestion-state-dir", "must be an existing directory");
        require(Files.isDirectory(rootPath), "artifact-root", "must be an existing directory");
        try {
            require(rootPath.equals(rootPath.toRealPath()), "artifact-root",
                    "must be a real path without symbolic links");
            Path realState = statePath.toRealPath();
            require(!rootPath.startsWith(realState) && !realState.startsWith(rootPath), "artifact-root",
                    "must not contain or lie inside the ingestion state directory");
            // The S2-1 CLI rejects a state directory that holds any file it does not own.
            require(!requestPath.toRealPath().startsWith(realState), "request",
                    "must not lie inside the ingestion state directory");
            Path parent = resultPath.getParent();
            require(parent != null && Files.isDirectory(parent), "result", "must have an existing parent directory");
            require(!parent.toRealPath().startsWith(realState), "result",
                    "must not lie inside the ingestion state directory");
        } catch (IOException error) {
            throw new DocumentImportConfigurationException("artifact-root", "cannot be resolved");
        }
        require(!Files.exists(resultPath, LinkOption.NOFOLLOW_LINKS), "result", "must not exist yet");
        return new DocumentImportSettings(requestPath, resultPath, cliPath, statePath, sourcesPath, rootPath);
    }

    private static Path absolute(String setting, String value) {
        if (value == null || value.isBlank()) {
            throw new DocumentImportConfigurationException(setting, "must be set");
        }
        try {
            Path path = Path.of(value);
            if (!path.isAbsolute() || !path.equals(path.normalize())) {
                throw new DocumentImportConfigurationException(setting, "must be a normalized absolute path");
            }
            return path;
        } catch (InvalidPathException error) {
            throw new DocumentImportConfigurationException(setting, "must be a valid path");
        }
    }

    private static void require(boolean condition, String setting, String rule) {
        if (!condition) {
            throw new DocumentImportConfigurationException(setting, rule);
        }
    }
}
