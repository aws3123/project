package com.acme.review.config;

import java.util.List;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.springframework.boot.context.properties.ConfigurationProperties;

@Getter
@Setter
@NoArgsConstructor
@ConfigurationProperties(prefix = "review.dispatch")
public class ReviewDispatchProperties {
    private int smallDiffChars = 4000;
    private int largeDiffChars = 12000;
    private int smallFileCount = 2;
    private int largeFileCount = 6;
    private double classifierConfidenceThreshold = 0.80;
    private List<String> highRiskKeywords = List.of(
            "ALTER TABLE",
            "DROP TABLE",
            "DELETE FROM",
            "@RequestMapping",
            "@GetMapping",
            "@PostMapping",
            "security",
            "token",
            "permission",
            "application.yml",
            "application-prod"
    );
    private List<String> quickIntentKeywords = List.of("快速", "概览", "简要", "立即", "先给结论");
    private List<String> deepIntentKeywords = List.of("全面", "深入", "详细", "完整", "发布前", "数据库", "接口", "配置", "风险");
}
