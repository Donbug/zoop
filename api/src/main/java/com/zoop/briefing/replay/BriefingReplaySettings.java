package com.zoop.briefing.replay;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermission;
import java.io.IOException;

/** Explicit private files for an operator-run historical development replay; none is a secret/API key. */
public record BriefingReplaySettings(Path source, Path bundle, Path artifactRoot, Path grants, Path manifest,
        String expectedSourceSha256, String userInboxRef, Path clocks, int maximumPaidCalls, String budgetApprovalRef) {
    public BriefingReplaySettings(Path source, Path bundle, Path artifactRoot, Path grants, Path manifest,
            String expectedSourceSha256, String userInboxRef, Path clocks) {
        this(source, bundle, artifactRoot, grants, manifest, expectedSourceSha256, userInboxRef, clocks, 400, null);
    }
    public BriefingReplaySettings(Path source, Path bundle, Path artifactRoot, Path grants, Path manifest,
            String expectedSourceSha256, String userInboxRef) {
        this(source, bundle, artifactRoot, grants, manifest, expectedSourceSha256, userInboxRef, null);
    }

    public BriefingReplaySettings {
        for (Path p : new Path[] {source, bundle, artifactRoot, grants, manifest}) {
            if (p == null || !p.isAbsolute() || !p.equals(p.normalize())) invalid();
        }
        if (!Files.isRegularFile(source) || !Files.isRegularFile(bundle) || !Files.isDirectory(artifactRoot)
                || !Files.isDirectory(grants.getParent()) || !Files.isDirectory(manifest.getParent())
                || source.equals(bundle) || grants.equals(manifest) || grants.equals(source) || grants.equals(bundle)
                || manifest.equals(source) || manifest.equals(bundle)) invalid();
        if (expectedSourceSha256 == null || !expectedSourceSha256.matches("[0-9a-f]{64}")
                || userInboxRef == null || !(userInboxRef.matches("inbox/[A-Za-z0-9_.-]+\\.md")
                    || userInboxRef.matches("local:BRF-[A-Za-z0-9:._-]{1,180}"))) invalid();
        if (maximumPaidCalls < 1 || maximumPaidCalls > 512
                || (maximumPaidCalls > 400 && (budgetApprovalRef == null
                    || !budgetApprovalRef.matches("inbox/[A-Za-z0-9_.-]+\\.md")))) invalid();
        if (clocks != null && (!clocks.isAbsolute() || !clocks.equals(clocks.normalize()) || !Files.isRegularFile(clocks))) invalid();
        for (Path parent : new Path[] {grants.getParent(), manifest.getParent()}) {
            try {
                var permissions = Files.getPosixFilePermissions(parent);
                if (!parent.equals(parent.toRealPath()) || permissions.contains(PosixFilePermission.GROUP_WRITE)
                        || permissions.contains(PosixFilePermission.OTHERS_WRITE)) invalid();
            } catch (IOException error) { invalid(); }
        }
    }

    private static void invalid() { throw new IllegalArgumentException("Invalid private briefing replay setting"); }
}
