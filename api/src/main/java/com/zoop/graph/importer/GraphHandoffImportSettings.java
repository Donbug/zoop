package com.zoop.graph.importer;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.InvalidPathException;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.util.List;

/**
 * Validated paths of an enabled operator graph handoff import. Every path is absolute and normalized. The request, the
 * source registry and the three operator files are regular files; both CLIs are executable; the four ledger directories and
 * the artifact root are existing directories. The artifact root has no symlink component and does not contain or lie inside a
 * ledger directory, and neither the request, the result nor an operator file lies inside a ledger directory (each CLI rejects a
 * state directory that holds a file it does not own). The result file does not exist yet and its parent does. Nothing here is a
 * secret, but a failure still names only the setting.
 *
 * <p>There is exactly ONE source registry and ONE S2-1 ledger: the handoff export and the per-observation
 * {@code zoop-ai-ingest export --require-store} both read {@code ingestionSources} and {@code ingestionState}, so the rights
 * the handoff was checked against and the rights the app persists under are never two different files.
 *
 * @param request         operator request JSON
 * @param result          result file, created exclusively by the run
 * @param handoffCli      the installed {@code zoop-ai-handoff} executable
 * @param handoffState    the handoff ledger directory (the CLI opens it read-only for an export)
 * @param relationState   the S3 relation ledger directory
 * @param extractionState the S2 extraction ledger directory
 * @param ingestionCli    the installed {@code zoop-ai-ingest} executable
 * @param ingestionState  the S2-1 ledger directory
 * @param ingestionSources the current operator source registry, which is the rights authority of both CLIs
 * @param canonical       the operator canonical registry file the handoff was frozen with
 * @param decisions       the operator public-projection decisions file the handoff was frozen with
 * @param bindings        the server-owned app document bindings file the handoff was frozen with
 * @param artifactRoot    root of the local artifact file store
 */
public record GraphHandoffImportSettings(Path request, Path result, Path handoffCli, Path handoffState,
        Path relationState, Path extractionState, Path ingestionCli, Path ingestionState, Path ingestionSources,
        Path canonical, Path decisions, Path bindings, Path artifactRoot) {

    public static GraphHandoffImportSettings of(GraphHandoffImportProperties p) {
        Path request = absolute("request", p.request());
        Path result = absolute("result", p.result());
        Path handoffCli = absolute("handoff-cli", p.handoffCli());
        Path handoffState = absolute("handoff-state-dir", p.handoffStateDir());
        Path relationState = absolute("relation-state-dir", p.relationStateDir());
        Path extractionState = absolute("extraction-state-dir", p.extractionStateDir());
        Path ingestionCli = absolute("ingestion-cli", p.ingestionCli());
        Path ingestionState = absolute("ingestion-state-dir", p.ingestionStateDir());
        Path sources = absolute("ingestion-sources", p.ingestionSources());
        Path canonical = absolute("canonical", p.canonical());
        Path decisions = absolute("decisions", p.decisions());
        Path bindings = absolute("bindings", p.bindings());
        Path root = absolute("artifact-root", p.artifactRoot());

        require(Files.isRegularFile(request), "request", "must be an existing file");
        require(Files.isRegularFile(handoffCli) && Files.isExecutable(handoffCli), "handoff-cli",
                "must be an existing executable file");
        require(Files.isRegularFile(ingestionCli) && Files.isExecutable(ingestionCli), "ingestion-cli",
                "must be an existing executable file");
        require(Files.isRegularFile(sources), "ingestion-sources", "must be an existing file");
        require(Files.isRegularFile(canonical), "canonical", "must be an existing file");
        require(Files.isRegularFile(decisions), "decisions", "must be an existing file");
        require(Files.isRegularFile(bindings), "bindings", "must be an existing file");
        require(Files.isDirectory(handoffState), "handoff-state-dir", "must be an existing directory");
        require(Files.isDirectory(relationState), "relation-state-dir", "must be an existing directory");
        require(Files.isDirectory(extractionState), "extraction-state-dir", "must be an existing directory");
        require(Files.isDirectory(ingestionState), "ingestion-state-dir", "must be an existing directory");
        require(Files.isDirectory(root), "artifact-root", "must be an existing directory");
        try {
            require(root.equals(root.toRealPath()), "artifact-root", "must be a real path without symbolic links");
            List<Path> ledgers = List.of(handoffState.toRealPath(), relationState.toRealPath(),
                    extractionState.toRealPath(), ingestionState.toRealPath());
            for (Path ledger : ledgers) {
                require(!root.startsWith(ledger) && !ledger.startsWith(root), "artifact-root",
                        "must not contain or lie inside a ledger state directory");
                require(!request.toRealPath().startsWith(ledger), "request", "must not lie inside a ledger state directory");
                require(!canonical.toRealPath().startsWith(ledger) && !decisions.toRealPath().startsWith(ledger)
                        && !bindings.toRealPath().startsWith(ledger), "canonical",
                        "operator files must not lie inside a ledger state directory");
            }
            Path parent = result.getParent();
            require(parent != null && Files.isDirectory(parent), "result", "must have an existing parent directory");
            for (Path ledger : ledgers) {
                require(!parent.toRealPath().startsWith(ledger), "result", "must not lie inside a ledger state directory");
            }
        } catch (IOException error) {
            throw new GraphHandoffImportConfigurationException("artifact-root", "cannot be resolved");
        }
        require(!Files.exists(result, LinkOption.NOFOLLOW_LINKS), "result", "must not exist yet");
        return new GraphHandoffImportSettings(request, result, handoffCli, handoffState, relationState, extractionState,
                ingestionCli, ingestionState, sources, canonical, decisions, bindings, root);
    }

    private static Path absolute(String setting, String value) {
        if (value == null || value.isBlank()) {
            throw new GraphHandoffImportConfigurationException(setting, "must be set");
        }
        try {
            Path path = Path.of(value);
            if (!path.isAbsolute() || !path.equals(path.normalize())) {
                throw new GraphHandoffImportConfigurationException(setting, "must be a normalized absolute path");
            }
            return path;
        } catch (InvalidPathException error) {
            throw new GraphHandoffImportConfigurationException(setting, "must be a valid path");
        }
    }

    private static void require(boolean condition, String setting, String rule) {
        if (!condition) {
            throw new GraphHandoffImportConfigurationException(setting, rule);
        }
    }
}
