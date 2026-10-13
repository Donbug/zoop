package com.zoop.auth.service;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.IOException;
import java.time.Instant;
import java.util.Base64;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;

final class TermsCursor {
    private static final int VERSION = 1;
    private static final int MAX_ENCODED_LENGTH = 4096;

    private TermsCursor() {
    }

    static String encode(Instant asOf, String afterId, int limit) {
        try {
            var bytes = new ByteArrayOutputStream();
            var output = new DataOutputStream(bytes);
            output.writeByte(VERSION);
            output.writeLong(asOf.getEpochSecond());
            output.writeInt(asOf.getNano());
            output.writeInt(limit);
            output.writeUTF(afterId);
            output.flush();
            return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes.toByteArray());
        } catch (IOException exception) {
            throw new IllegalStateException("Cannot encode terms cursor", exception);
        }
    }

    static Decoded decode(String value, Instant now) {
        if (value == null || value.isBlank() || value.length() > MAX_ENCODED_LENGTH) {
            throw invalid();
        }
        try {
            byte[] bytes = Base64.getUrlDecoder().decode(value);
            var input = new DataInputStream(new ByteArrayInputStream(bytes));
            int version = input.readUnsignedByte();
            Instant asOf = Instant.ofEpochSecond(input.readLong(), input.readInt());
            int limit = input.readInt();
            String afterId = input.readUTF();
            if (version != VERSION || limit < 1 || afterId.isBlank()
                    || asOf.isAfter(now) || input.available() != 0) {
                throw invalid();
            }
            return new Decoded(asOf, afterId, limit);
        } catch (IllegalArgumentException | IOException exception) {
            throw invalid();
        }
    }

    private static CustomException invalid() {
        return new CustomException(ErrorCode.INVALID_CURSOR);
    }

    record Decoded(Instant asOf, String afterId, int limit) {
    }
}
