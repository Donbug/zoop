package com.zoop.admin.transcripts;

import com.zoop.admin.auth.config.AdminPermissions;
import com.zoop.admin.auth.service.AdminPrincipal;
import java.util.Arrays;
import java.util.Set;
import java.util.stream.Collectors;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/** FS066-03: admin:all alone never grants transcript:read. Empty by default. */
@Component
public class TranscriptReadPolicy {
    public static final String PERMISSION = "transcript:read";
    private final Set<String> readers;

    public TranscriptReadPolicy(@Value("${zoop.admin.transcript-readers:}") String configuredReaders) {
        readers = Arrays.stream(configuredReaders.split(",", -1)).map(String::strip)
                .filter(s -> !s.isEmpty()).collect(Collectors.toUnmodifiableSet());
    }

    public boolean allows(AdminPrincipal admin) {
        return admin != null && AdminPermissions.can(admin.role(), "admin:all")
                && readers.contains(admin.adminId());
    }
}
