package com.acme.review;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;
import org.springframework.scheduling.annotation.EnableScheduling;

@SpringBootApplication
@ConfigurationPropertiesScan
@MapperScan("com.acme.review.repository.mapper")
@EnableScheduling
public class ReviewBackendApplication {

    public static void main(String[] args) {
        SpringApplication.run(ReviewBackendApplication.class, args);
    }
}
