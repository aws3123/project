package com.acme.review.controller;

import com.acme.review.config.ApiAuthenticationEntryPoint;
import com.acme.review.config.ApiKeyAuthenticationFilter;
import com.acme.review.config.SecurityConfig;
import com.acme.review.config.SecurityProperties;
import com.acme.review.dto.SseBusinessRiskEvent;
import com.acme.review.service.BusinessRiskSseService;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.autoconfigure.ImportAutoConfiguration;
import org.springframework.boot.autoconfigure.jdbc.DataSourceAutoConfiguration;
import org.springframework.boot.autoconfigure.jdbc.DataSourceTransactionManagerAutoConfiguration;
import org.springframework.boot.autoconfigure.jdbc.JdbcTemplateAutoConfiguration;
import org.springframework.boot.autoconfigure.orm.jpa.HibernateJpaAutoConfiguration;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import reactor.core.publisher.Flux;

import static org.mockito.ArgumentMatchers.eq;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(controllers = BusinessRiskSseController.class)
@AutoConfigureMockMvc
@ImportAutoConfiguration(exclude = {
        DataSourceAutoConfiguration.class,
        DataSourceTransactionManagerAutoConfiguration.class,
        JdbcTemplateAutoConfiguration.class,
        HibernateJpaAutoConfiguration.class
})
@Import({SecurityConfig.class, BusinessRiskSseControllerTest.SecurityTestConfig.class})
class BusinessRiskSseControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @MockBean
    private BusinessRiskSseService sseService;

    @Test
    void streamShouldReturnSseContentType() throws Exception {
        Mockito.when(sseService.replayFrom(eq("session-1"), eq("100")))
                .thenReturn(Flux.just(new SseBusinessRiskEvent("101", "session-1", "task-1", "processing", "{\"status\":\"PROCESSING\"}")));
        Mockito.when(sseService.liveStream(eq("session-1")))
                .thenReturn(Flux.empty());

        mockMvc.perform(get("/api/business-risk/stream")
                        .header("X-API-Key", "test-key")
                        .param("sessionId", "session-1")
                        .header("Last-Event-ID", "100"))
                .andExpect(status().isOk())
                .andExpect(header().string("Content-Type", org.hamcrest.Matchers.containsString(MediaType.TEXT_EVENT_STREAM_VALUE)));
    }

    @TestConfiguration
    static class SecurityTestConfig {
        @Bean
        SecurityProperties securityProperties() {
            return new SecurityProperties("X-API-Key", "test-key", "callback-token");
        }

        @Bean
        ApiAuthenticationEntryPoint apiAuthenticationEntryPoint() {
            return new ApiAuthenticationEntryPoint();
        }

        @Bean
        ApiKeyAuthenticationFilter apiKeyAuthenticationFilter(SecurityProperties securityProperties) {
            return new ApiKeyAuthenticationFilter(securityProperties);
        }
    }
}
