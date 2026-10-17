package com.zoop.common.config;

import io.swagger.v3.oas.models.Components;
import io.swagger.v3.oas.models.OpenAPI;
import io.swagger.v3.oas.models.info.Info;
import io.swagger.v3.oas.models.security.SecurityScheme;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class SwaggerConfig {
    public static final String CSRF_SCHEME = "X-CSRF-Token";
    public static final String SESSION_COOKIE_SCHEME = "zoop_session_cookie";

    @Bean
    public OpenAPI openAPI() {
        return new OpenAPI()
                .info(new Info()
                        .title("ZOOP API 명세서")
                        .description("현재 구현된 ZOOP HTTP API 문서입니다. 회원/비회원 세션 쿠키가 포함된 쓰기 요청은 허용 Origin과 세션 결합 CSRF 토큰이 필요합니다. OpenAPI 보안 스키마는 문서용이며 브라우저 Swagger UI가 HttpOnly 세션 쿠키를 직접 설정하지는 않습니다. 목표 계약은 docs/api/openapi.yaml을 참고하세요.")
                        .version("v1.0.0"))
                .components(new Components()
                        .addSecuritySchemes(CSRF_SCHEME, new SecurityScheme()
                                .type(SecurityScheme.Type.APIKEY)
                                .in(SecurityScheme.In.HEADER)
                                .name(CSRF_SCHEME)
                                .description("회원/비회원 세션 쿠키가 포함된 쓰기 요청에 필요한 세션 결합 CSRF 토큰. Origin 검증도 함께 적용됩니다."))
                        .addSecuritySchemes(SESSION_COOKIE_SCHEME, new SecurityScheme()
                                .type(SecurityScheme.Type.APIKEY)
                                .in(SecurityScheme.In.COOKIE)
                                .name("zoop_session")
                                .description("회원 또는 비회원 세션 쿠키. HttpOnly 쿠키이므로 브라우저 JavaScript/Swagger UI에서 임의 설정할 수 없습니다.")));
    }
}
