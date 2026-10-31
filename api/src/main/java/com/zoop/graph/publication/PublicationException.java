package com.zoop.graph.publication;

public final class PublicationException extends RuntimeException {
    private final String code;

    public PublicationException(String code) {
        super(code, null, false, false);
        this.code = code;
    }

    public String code() { return code; }
}
