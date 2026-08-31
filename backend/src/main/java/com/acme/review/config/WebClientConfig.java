package com.acme.review.config;

import io.netty.channel.ChannelOption;
import io.netty.handler.timeout.ReadTimeoutHandler;
import io.netty.handler.timeout.WriteTimeoutHandler;
import org.springframework.boot.web.reactive.function.client.WebClientCustomizer;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.reactive.ReactorClientHttpConnector;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.web.reactive.function.client.ExchangeStrategies;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.netty.http.client.HttpClient;

import java.time.Duration;
import java.util.concurrent.TimeUnit;

@Configuration
@EnableConfigurationProperties(PythonClientProperties.class)
public class WebClientConfig {

    @Bean
    public WebClient pythonWebClient(PythonClientProperties pythonClientProperties) {
        HttpClient httpClient = HttpClient.create()
                .option(ChannelOption.CONNECT_TIMEOUT_MILLIS, pythonClientProperties.getConnectTimeoutMs())
                .responseTimeout(Duration.ofMillis(pythonClientProperties.getTimeoutMs()))
                .doOnConnected(conn -> conn
                        .addHandlerLast(new ReadTimeoutHandler(pythonClientProperties.getTimeoutMs(), TimeUnit.MILLISECONDS))
                        .addHandlerLast(new WriteTimeoutHandler(pythonClientProperties.getTimeoutMs(), TimeUnit.MILLISECONDS))
                );

        return WebClient.builder()
                .baseUrl(pythonClientProperties.getBaseUrl())
                .clientConnector(new ReactorClientHttpConnector(httpClient))
                .exchangeStrategies(ExchangeStrategies.builder()
                        .codecs(configurer -> configurer.defaultCodecs().maxInMemorySize(2 * 1024 * 1024))
                        .build())
                .build();
    }
}
