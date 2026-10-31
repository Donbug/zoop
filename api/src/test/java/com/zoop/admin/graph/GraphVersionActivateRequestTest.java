package com.zoop.admin.graph;

import jakarta.validation.Validation;
import jakarta.validation.Validator;
import org.junit.jupiter.api.Test;
import tools.jackson.core.JacksonException;
import tools.jackson.databind.json.JsonMapper;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** Review 3: the field is required but nullable, so "absent" (422) and "explicit null" (none was active) must differ. */
class GraphVersionActivateRequestTest {
    private final JsonMapper mapper = JsonMapper.builder().build();
    private final Validator validator = Validation.buildDefaultValidatorFactory().getValidator();

    @Test
    void absentExpectedVersionDoesNotBind() {
        // Spring turns this binding failure into HttpMessageNotReadableException, mapped to 422 INVALID_REQUEST.
        assertThrows(JacksonException.class,
                () -> mapper.readValue("{\"reason\":\"go\"}", GraphVersionActivateRequest.class));
    }

    @Test
    void explicitNullAndAValueBind() {
        var explicitNull = mapper.readValue("{\"reason\":\"go\",\"expectedActiveVersionId\":null}",
                GraphVersionActivateRequest.class);
        var value = mapper.readValue("{\"reason\":\"go\",\"expectedActiveVersionId\":\"gv-1\"}",
                GraphVersionActivateRequest.class);

        assertNull(explicitNull.expectedActiveVersionId());
        assertEquals("forward", explicitNull.mode());
        assertTrue(validator.validate(explicitNull).isEmpty());
        assertEquals("gv-1", value.expectedActiveVersionId());
        assertTrue(validator.validate(value).isEmpty());
    }

    @Test
    void explicitModesBindAndOtherValuesFailValidation() {
        for (String mode : new String[] {"forward", "rollback"}) {
            var request = mapper.readValue(
                    "{\"reason\":\"go\",\"expectedActiveVersionId\":null,\"mode\":\"" + mode + "\"}",
                    GraphVersionActivateRequest.class);
            assertEquals(mode, request.mode());
            assertTrue(validator.validate(request).isEmpty());
        }
        for (String mode : new String[] {"", "ROLLBACK", "replace", " forward "}) {
            assertFalse(validator.validate(new GraphVersionActivateRequest("go", null, mode)).isEmpty());
        }
    }

    @Test
    void overlongExpectedVersionIsInvalid() {
        assertFalse(validator.validate(new GraphVersionActivateRequest("go", "v".repeat(121), "forward")).isEmpty());
    }
}
