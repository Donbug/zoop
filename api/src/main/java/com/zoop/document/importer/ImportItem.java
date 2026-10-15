package com.zoop.document.importer;

import com.zoop.document.service.ArticleKind;
import com.zoop.document.service.PointerPolicy;

/** One operator-declared document version to import. */
public record ImportItem(ArticleKind kind, Observation observation, PointerPolicy pointer) {
}
