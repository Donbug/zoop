package com.zoop.common.exception;

import com.jayway.jsonpath.JsonPath;
import com.zoop.common.request.RequestIdFilter;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.validation.beanvalidation.LocalValidatorFactoryBean;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import static org.hamcrest.Matchers.not;
import static org.hamcrest.Matchers.blankOrNullString;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class GlobalExceptionHandlerTest {
    private MockMvc mvc;

    @BeforeEach
    void setUp() {
        LocalValidatorFactoryBean validator = new LocalValidatorFactoryBean();
        validator.afterPropertiesSet();
        mvc = MockMvcBuilders.standaloneSetup(new TestController())
                .setControllerAdvice(new GlobalExceptionHandler())
                .setValidator(validator)
                .addFilters(new RequestIdFilter())
                .build();
    }

    @Test
    void invalidBodyUsesContractAndKeepsProvidedRequestId() throws Exception {
        mvc.perform(post("/test/values").header(RequestIdFilter.HEADER, "req-123")
                        .contentType(MediaType.APPLICATION_JSON).content("{\"value\":\"\"}"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(header().string(RequestIdFilter.HEADER, "req-123"))
                .andExpect(jsonPath("$.error.code").value("INVALID_REQUEST"))
                .andExpect(jsonPath("$.error.requestId").value("req-123"))
                .andExpect(jsonPath("$.error.retryable").value(false))
                .andExpect(jsonPath("$.error.details").doesNotExist());
    }

    @Test
    void malformedJsonAndPathTypeMismatchAreInvalidRequests() throws Exception {
        mvc.perform(post("/test/values").contentType(MediaType.APPLICATION_JSON).content("{"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.code").value("INVALID_REQUEST"));

        mvc.perform(get("/test/values/not-a-number"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.code").value("INVALID_REQUEST"));
    }

    @Test
    void customExceptionUsesItsCode() throws Exception {
        mvc.perform(get("/test/missing"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.error.code").value("RESOURCE_NOT_FOUND"));
    }

    @Test
    void unexpectedExceptionDoesNotExposeInternalMessage() throws Exception {
        var result = mvc.perform(get("/test/failure"))
                .andExpect(status().isInternalServerError())
                .andExpect(jsonPath("$.error.code").value("INTERNAL_ERROR"))
                .andExpect(jsonPath("$.error.message").value("서버 오류가 발생했습니다."))
                .andExpect(jsonPath("$.error.requestId", not(blankOrNullString())))
                .andReturn();
        org.junit.jupiter.api.Assertions.assertEquals(
                result.getResponse().getHeader(RequestIdFilter.HEADER),
                JsonPath.read(result.getResponse().getContentAsString(), "$.error.requestId"));
        org.junit.jupiter.api.Assertions.assertFalse(result.getResponse().getContentAsString().contains("private internal detail"));
    }

    @Test
    void generatedIdAlsoAppearsOnSuccessfulResponse() throws Exception {
        mvc.perform(get("/test/ok"))
                .andExpect(status().isOk())
                .andExpect(header().exists(RequestIdFilter.HEADER));
    }

    @Test
    void unsupportedMethodKeeps405() throws Exception {
        mvc.perform(post("/test/ok"))
                .andExpect(status().isMethodNotAllowed())
                .andExpect(jsonPath("$.error.code").value("INVALID_REQUEST"));
    }

    @RestController
    @RequestMapping("/test")
    static class TestController {
        @PostMapping("/values")
        String accept(@Valid @RequestBody ValueRequest body) {
            return body.value();
        }

        @GetMapping("/values/{number}")
        int number(@PathVariable int number) {
            return number;
        }

        @GetMapping("/missing")
        String missing() {
            throw new CustomException(ErrorCode.RESOURCE_NOT_FOUND);
        }

        @GetMapping("/failure")
        String failure() {
            throw new IllegalStateException("private internal detail");
        }

        @GetMapping("/ok")
        String ok() {
            return "ok";
        }
    }

    record ValueRequest(@NotBlank String value) {
    }
}
