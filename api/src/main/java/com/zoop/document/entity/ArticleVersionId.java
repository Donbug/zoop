package com.zoop.document.entity;

import java.io.Serializable;
import java.util.Objects;

public class ArticleVersionId implements Serializable {
    private String articleId;
    private String version;

    public ArticleVersionId() {
    }

    public ArticleVersionId(String articleId, String version) {
        this.articleId = articleId;
        this.version = version;
    }

    @Override
    public boolean equals(Object other) {
        if (this == other) {
            return true;
        }
        if (!(other instanceof ArticleVersionId that)) {
            return false;
        }
        return Objects.equals(articleId, that.articleId)
            && Objects.equals(version, that.version);
    }

    @Override
    public int hashCode() {
        return Objects.hash(articleId, version);
    }
}
