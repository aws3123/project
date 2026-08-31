package com.acme.review.dto;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class BusinessRiskLineMapJsonTest {

    @Test
    void shouldSerializeSnakeCaseFieldNames() throws Exception {
        BusinessRiskLineMap lineMap = new BusinessRiskLineMap();
        lineMap.setStartLine(7);
        lineMap.setEndLine(11);

        String json = new ObjectMapper().writeValueAsString(lineMap);

        assertThat(json).contains("\"start_line\":7");
        assertThat(json).contains("\"end_line\":11");
        assertThat(json).doesNotContain("startLine");
        assertThat(json).doesNotContain("endLine");
    }
}
