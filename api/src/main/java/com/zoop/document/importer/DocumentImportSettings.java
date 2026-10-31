package com.zoop.document.importer;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.InvalidPathException;
import java.nio.file.LinkOption;
import java.nio.file.Path;

/**
 * Validated paths of an enabled operator import. Every path is absolute; the request is a regular file; the artifact root is
 * an existing directory without a symlink component; the result file does not exist yet and its parent does. With the CLI
 * observation source (the default) the S2-1 CLI and sources registry are regular files, the CLI is executable, the S2-1 state
 * directory exists and does not contain or lie inside the artifact root. With {@code observationSource=http} the observations
 * come from ai/service's observation export route instead ({@code zoop.ai.observation-export-client}), no CLI runs here and
 * the three CLI settings must be left unset: an operator run on a host without the AI CLIs (an ECS task) names nothing it does
 * not use. Nothing here is a secret, but a failure still names only the setting.
 *
 * @param request       operator request JSON
 * @param result        result file, created exclusively by the run
 * @param ingestionCli  the installed {@code zoop-ai-ingest} executable (CLI source only; null with http)
 * @param ingestionState the S2-1 ledger directory (CLI source only; null with http)
 * @param ingestionSources the current operator source registry, the import authority of the CLI source (null with http: the
 *                      AI service's current registry is the authority then)
 * @param artifactRoot  root of the local artifact file store
 * @param observationSource where each observation's text and current rights come from
 */
public record DocumentImportSettings(Path request, Path result, Path ingestionCli, Path ingestionState,
        Path ingestionSources, Path artifactRoot, ObservationSource observationSource) {

    public static DocumentImportSettings of(String request, String result, String ingestionCli, String ingestionState,
            String ingestionSources, String artifactRoot, String observationSource) {
        ObservationSource source = ObservationSource.parse(observationSource)
                .orElseThrow(() -> new DocumentImportConfigurationException("observation-source", "must be cli or http"));
        boolean cli = source == ObservationSource.CLI;
        Path requestPath = absolute("request", request);
        Path resultPath = absolute("result", result);
        Path cliPath = cliOnly(cli, "ingestion-cli", ingestionCli);
        Path statePath = cliOnly(cli, "ingestion-state-dir", ingestionState);
        Path sourcesPath = cliOnly(cli, "ingestion-sources", ingestionSources);
        Path rootPath = absolute("artifact-root", artifactRoot);

        require(Files.isRegularFile(requestPath), "request", "must be an existing file");
        if (cli) {
            require(Files.isRegularFile(cliPath) && Files.isExecutable(cliPath), "ingestion-cli",
                    "must be an existing executable file");
            require(Files.isRegularFile(sourcesPath), "ingestion-sources", "must be an existing file");
            require(Files.isDirectory(statePath), "ingestion-state-dir", "must be an existing directory");
        }
        require(Files.isDirectory(rootPath), "artifact-root", "must be an existing directory");
        try {
            require(rootPath.equals(rootPath.toRealPath()), "artifact-root",
                    "must be a real path without symbolic links");
            Path parent = resultPath.getParent();
            require(parent != null && Files.isDirectory(parent), "result", "must have an existing parent directory");
            if (cli) {
                Path realState = statePath.toRealPath();
                require(!rootPath.startsWith(realState) && !realState.startsWith(rootPath), "artifact-root",
                        "must not contain or lie inside the ingestion state directory");
                // The S2-1 CLI rejects a state directory that holds any file it does not own.
                require(!requestPath.toRealPath().startsWith(realState), "request",
                        "must not lie inside the ingestion state directory");
                require(!parent.toRealPath().startsWith(realState), "result",
                        "must not lie inside the ingestion state directory");
            }
        } catch (IOException error) {
            throw new DocumentImportConfigurationException("artifact-root", "cannot be resolved");
        }
        require(!Files.exists(resultPath, LinkOption.NOFOLLOW_LINKS), "result", "must not exist yet");
        return new DocumentImportSettings(requestPath, resultPath, cliPath, statePath, sourcesPath, rootPath, source);
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

    /** A CLI-only setting: required with the CLI source, refused (not ignored) with the HTTP source. */
    private static Path cliOnly(boolean cli, String setting, String value) {
        if (cli) {
            return absolute(setting, value);
        }
        if (value != null && !value.isBlank()) {
            throw new DocumentImportConfigurationException(setting, "must not be set with observation-source=http");
        }
        return null;
    }

    private static void require(boolean condition, String setting, String rule) {
        if (!condition) {
            throw new DocumentImportConfigurationException(setting, rule);
        }
    }
}
