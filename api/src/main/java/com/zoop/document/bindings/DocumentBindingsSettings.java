package com.zoop.document.bindings;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.InvalidPathException;
import java.nio.file.LinkOption;
import java.nio.file.Path;

/**
 * Validated settings of an enabled export. The output (the bindings file) and the result are normalized absolute paths that
 * do not exist yet, in existing directories, and name different files even through symbolic links in their directories; the
 * optional selection is an existing regular file. Nothing here is a secret, but a failure still names only the setting.
 *
 * @param output    the bindings file to create exclusively ({@code zoop-app-document-bindings-1})
 * @param result    the result file to create exclusively
 * @param selection the operator's selection file, or {@code null} to bind every registered version in scope
 * @param scope     which versions to bind
 */
public record DocumentBindingsSettings(Path output, Path result, Path selection, DocumentBindingsScope scope) {
    public static DocumentBindingsSettings of(String output, String result, String selection, String scope) {
        Path outputPath = absolute("output", output);
        Path resultPath = absolute("result", result);
        Path selectionPath = selection == null || selection.isBlank() ? null : absolute("selection", selection);
        DocumentBindingsScope parsedScope = DocumentBindingsScope.parse(scope);
        if (parsedScope == null) {
            throw new DocumentBindingsConfigurationException("scope", "must be available or all");
        }
        Path outputReal = requireNew("output", outputPath);
        Path resultReal = requireNew("result", resultPath);
        if (outputReal.equals(resultReal)) {
            throw new DocumentBindingsConfigurationException("result", "must differ from output");
        }
        if (selectionPath != null && !Files.isRegularFile(selectionPath)) {
            throw new DocumentBindingsConfigurationException("selection", "must be an existing file");
        }
        return new DocumentBindingsSettings(outputPath, resultPath, selectionPath, parsedScope);
    }

    /** The file does not exist (not even as a link) and its directory does; returns the file under its directory's real path. */
    private static Path requireNew(String setting, Path path) {
        Path parent = path.getParent();
        if (parent == null || !Files.isDirectory(parent)) {
            throw new DocumentBindingsConfigurationException(setting, "must have an existing parent directory");
        }
        Path real;
        try {
            real = parent.toRealPath().resolve(path.getFileName());
        } catch (IOException error) {
            throw new DocumentBindingsConfigurationException(setting, "cannot be resolved");
        }
        if (Files.exists(path, LinkOption.NOFOLLOW_LINKS)) {
            throw new DocumentBindingsConfigurationException(setting, "must not exist yet");
        }
        return real;
    }

    private static Path absolute(String setting, String value) {
        if (value == null || value.isBlank()) {
            throw new DocumentBindingsConfigurationException(setting, "must be set");
        }
        try {
            Path path = Path.of(value);
            if (!path.isAbsolute() || !path.equals(path.normalize())) {
                throw new DocumentBindingsConfigurationException(setting, "must be a normalized absolute path");
            }
            return path;
        } catch (InvalidPathException error) {
            throw new DocumentBindingsConfigurationException(setting, "must be a valid path");
        }
    }
}
