package com.zoop.common.config;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

class SwaggerConfigTest {
    private final SwaggerConfig config = new SwaggerConfig();

    @Test
    void documentsConditionalSessionSecurityWithoutMakingItGlobal() {
        var openApi = config.openAPI();

        assertThat(openApi.getInfo().getTitle()).isEqualTo("ZOOP API 명세서");
        assertThat(openApi.getSecurity()).isNull();
        assertThat(openApi.getComponents().getSecuritySchemes())
                .containsKeys(SwaggerConfig.CSRF_SCHEME, SwaggerConfig.SESSION_COOKIE_SCHEME);
        assertThat(openApi.getComponents().getSecuritySchemes().get(SwaggerConfig.CSRF_SCHEME).getName())
                .isEqualTo("X-CSRF-Token");
        assertThat(openApi.getComponents().getSecuritySchemes().get(SwaggerConfig.SESSION_COOKIE_SCHEME).getName())
                .isEqualTo("zoop_session");
    }
}
