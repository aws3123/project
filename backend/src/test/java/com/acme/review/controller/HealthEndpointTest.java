package com.acme.review.controller;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.actuate.health.Health;
import org.springframework.boot.actuate.health.HealthIndicator;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.BDDMockito.given;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
class HealthEndpointTest {

    @Autowired
    private MockMvc mockMvc;

    @MockBean(name = "python")
    private HealthIndicator pythonHealthIndicator;

    @BeforeEach
    void setUp() {
        given(pythonHealthIndicator.health()).willReturn(Health.down().withDetail("reason", "mock-down").build());
    }

    @Test
    void shouldExposeOverallHealthEndpoint() throws Exception {
        mockMvc.perform(get("/actuator/health"))
                .andExpect(status().is5xxServerError())
                .andExpect(jsonPath("$.status").value("DOWN"));
    }

    @Test
    void shouldExposeLivenessEndpoint() throws Exception {
        mockMvc.perform(get("/actuator/health/liveness"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("UP"));
    }

    @Test
    void shouldExposeReadinessEndpoint() throws Exception {
        mockMvc.perform(get("/actuator/health/readiness"))
                .andExpect(status().is5xxServerError())
                .andExpect(jsonPath("$.status").value("DOWN"));
    }

    @Test
    void shouldReturnDownWhenReadinessDependencyFails() throws Exception {
        mockMvc.perform(get("/actuator/health/readiness"))
                .andExpect(status().is5xxServerError())
                .andExpect(jsonPath("$.status").value("DOWN"))
                .andExpect(jsonPath("$.components.redisPing.status").value("DOWN"));
    }
}
