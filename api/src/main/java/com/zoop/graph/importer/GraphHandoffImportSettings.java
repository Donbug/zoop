package com.zoop.graph.importer;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.InvalidPathException;
import java.nio.file.LinkOption;
import java.nio.file.Path;

import com.zoop.document.importer.ObservationSource;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

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
 * <p>With {@code handoffSource=http} the handoff comes from ai/service's read-only handoff HTTP instead of the installed
 * {@code zoop-ai-handoff export}: the handoff CLI, the handoff, S3 and S2 ledger directories and the three operator files are
 * not read by this process and must be left unset (they are {@code null} here), because a value nobody uses would only suggest
 * an authority this run does not have.
 *
 * <p>With {@code observationSource=http} the per-observation rights check is ai/service's observation export route instead of
 * the installed {@code zoop-ai-ingest export --require-store}: {@code ingestionCli} is not run and must be left unset. The S2-1
 * ledger directory and the source registry are read by whichever CLI this process still runs (the handoff export with
 * {@code handoffSource=cli}, the observation export with {@code observationSource=cli}); when both sources are {@code http} no
 * CLI runs here and both must be left unset too (the AI service reads its own copies).
 *
 * @param handoffSource   where the current handoff comes from (blank is the documented default, {@code cli})
 * @param observationSource where each observation's current rights are checked (blank is the documented default, {@code cli})
 * @param request         operator request JSON
 * @param result          result file, created exclusively by the run
 * @param handoffCli      the installed {@code zoop-ai-handoff} executable (CLI source only)
 * @param handoffState    the handoff ledger directory (CLI source only; the CLI opens it read-only for an export)
 * @param relationState   the S3 relation ledger directory (CLI source only)
 * @param extractionState the S2 extraction ledger directory (CLI source only)
 * @param ingestionCli    the installed {@code zoop-ai-ingest} executable (CLI observation source only)
 * @param ingestionState  the S2-1 ledger directory (any CLI source; null when both sources are HTTP)
 * @param ingestionSources the current operator source registry, the rights authority of both CLIs (any CLI source; null when
 *                        both sources are HTTP)
 * @param canonical       the operator canonical registry file the handoff was frozen with (CLI source only)
 * @param decisions       the operator public-projection decisions file the handoff was frozen with (CLI source only)
 * @param bindings        the server-owned app document bindings file the handoff was frozen with (CLI source only)
 * @param artifactRoot    root of the local artifact file store
 */
public record GraphHandoffImportSettings(HandoffSourceKind handoffSource, ObservationSource observationSource, Path request,
        Path result, Path handoffCli, Path handoffState, Path relationState, Path extractionState, Path ingestionCli,
        Path ingestionState, Path ingestionSources, Path canonical, Path decisions, Path bindings, Path artifactRoot) {

    /** {@code cli}: the installed {@code zoop-ai-handoff export}; {@code http}: ai/service {@code getGraphHandoffBundle}. */
    public enum HandoffSourceKind {
        CLI, HTTP;

        static HandoffSourceKind parse(String value) {
            if (value == null || value.isBlank()) {
                return CLI; // the documented default; a variable listed with an empty value is no choice, like every other setting
            }
            return switch (value.strip().toLowerCase(Locale.ROOT)) {
                case "cli" -> CLI;
                case "http" -> HTTP;
                default -> throw new GraphHandoffImportConfigurationException("handoff-source", "must be cli or http");
            };
        }
    }

    /** The CLI source with every path set, as before the HTTP source existed. */
    public GraphHandoffImportSettings(Path request, Path result, Path handoffCli, Path handoffState, Path relationState,
            Path extractionState, Path ingestionCli, Path ingestionState, Path ingestionSources, Path canonical, Path decisions,
            Path bindings, Path artifactRoot) {
        this(HandoffSourceKind.CLI, ObservationSource.CLI, request, result, handoffCli, handoffState, relationState,
                extractionState, ingestionCli, ingestionState, ingestionSources, canonical, decisions, bindings, artifactRoot);
    }

    public static GraphHandoffImportSettings of(GraphHandoffImportProperties p) {
        HandoffSourceKind source = HandoffSourceKind.parse(p.handoffSource());
        ObservationSource observation = ObservationSource.parse(p.observationSource())
                .orElseThrow(() -> new GraphHandoffImportConfigurationException("observation-source", "must be cli or http"));
        boolean cli = source == HandoffSourceKind.CLI;
        boolean observationCli = observation == ObservationSource.CLI;
        boolean anyCli = cli || observationCli;
        Path request = absolute("request", p.request());
        Path result = absolute("result", p.result());
        Path handoffCli = cliOnly(cli, "handoff-cli", p.handoffCli(), "handoff-source=http");
        Path handoffState = cliOnly(cli, "handoff-state-dir", p.handoffStateDir(), "handoff-source=http");
        Path relationState = cliOnly(cli, "relation-state-dir", p.relationStateDir(), "handoff-source=http");
        Path extractionState = cliOnly(cli, "extraction-state-dir", p.extractionStateDir(), "handoff-source=http");
        Path ingestionCli = cliOnly(observationCli, "ingestion-cli", p.ingestionCli(), "observation-source=http");
        Path ingestionState = cliOnly(anyCli, "ingestion-state-dir", p.ingestionStateDir(),
                "handoff-source=http and observation-source=http");
        Path sources = cliOnly(anyCli, "ingestion-sources", p.ingestionSources(), "handoff-source=http and observation-source=http");
        Path canonical = cliOnly(cli, "canonical", p.canonical(), "handoff-source=http");
        Path decisions = cliOnly(cli, "decisions", p.decisions(), "handoff-source=http");
        Path bindings = cliOnly(cli, "bindings", p.bindings(), "handoff-source=http");
        Path root = absolute("artifact-root", p.artifactRoot());

        require(Files.isRegularFile(request), "request", "must be an existing file");
        if (observationCli) {
            require(Files.isRegularFile(ingestionCli) && Files.isExecutable(ingestionCli), "ingestion-cli",
                    "must be an existing executable file");
        }
        if (anyCli) {
            require(Files.isRegularFile(sources), "ingestion-sources", "must be an existing file");
            require(Files.isDirectory(ingestionState), "ingestion-state-dir", "must be an existing directory");
        }
        if (cli) {
            require(Files.isRegularFile(handoffCli) && Files.isExecutable(handoffCli), "handoff-cli",
                    "must be an existing executable file");
            require(Files.isRegularFile(canonical), "canonical", "must be an existing file");
            require(Files.isRegularFile(decisions), "decisions", "must be an existing file");
            require(Files.isRegularFile(bindings), "bindings", "must be an existing file");
            require(Files.isDirectory(handoffState), "handoff-state-dir", "must be an existing directory");
            require(Files.isDirectory(relationState), "relation-state-dir", "must be an existing directory");
            require(Files.isDirectory(extractionState), "extraction-state-dir", "must be an existing directory");
        }
        require(Files.isDirectory(root), "artifact-root", "must be an existing directory");
        try {
            require(root.equals(root.toRealPath()), "artifact-root", "must be a real path without symbolic links");
            List<Path> ledgers = new ArrayList<>();
            if (anyCli) {
                ledgers.add(ingestionState.toRealPath());
            }
            if (cli) {
                ledgers.add(handoffState.toRealPath());
                ledgers.add(relationState.toRealPath());
                ledgers.add(extractionState.toRealPath());
            }
            for (Path ledger : ledgers) {
                require(!root.startsWith(ledger) && !ledger.startsWith(root), "artifact-root",
                        "must not contain or lie inside a ledger state directory");
                require(!request.toRealPath().startsWith(ledger), "request", "must not lie inside a ledger state directory");
                if (cli) {
                    require(!canonical.toRealPath().startsWith(ledger) && !decisions.toRealPath().startsWith(ledger)
                            && !bindings.toRealPath().startsWith(ledger), "canonical",
                            "operator files must not lie inside a ledger state directory");
                }
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
        return new GraphHandoffImportSettings(source, observation, request, result, handoffCli, handoffState, relationState,
                extractionState, ingestionCli, ingestionState, sources, canonical, decisions, bindings, root);
    }

    /** A CLI-only setting: required while a CLI reads it, refused otherwise (nothing in this run would read it). */
    private static Path cliOnly(boolean cli, String setting, String value, String otherwise) {
        if (cli) {
            return absolute(setting, value);
        }
        if (value != null && !value.isBlank()) {
            throw new GraphHandoffImportConfigurationException(setting, "must not be set with " + otherwise);
        }
        return null;
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
