package com.acme.review.service;

import com.acme.review.ast.AstPreprocessedResult;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.DistributionSummary;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import org.springframework.stereotype.Service;

import java.util.function.Supplier;

/**
 * AST 预处理阶段指标：为「CPU 密集预处理前置 Java BFF」架构改造提供可观测性。
 *
 * <p>暴露指标（Prometheus 命名）：</p>
 * <ul>
 *   <li>review_ast_parse_seconds —— 单次 AST 预处理总耗时（配合 percentiles-histogram 输出分位数桶）</li>
 *   <li>review_ast_diff_bytes —— 进入预处理的 diff 载荷大小</li>
 *   <li>review_ast_files_parsed_total —— tree-sitter 原生解析成功的文件数</li>
 *   <li>review_ast_native_fallback_total —— 原生解析失败/无实体而回退正则路径的文件数</li>
 *   <li>review_ast_entities_extracted_total —— 原生路径提取出的 AST 实体累计数</li>
 * </ul>
 */
@Service
public class AstMetricsService {

    private final Timer parseTimer;
    private final DistributionSummary diffBytes;
    private final Counter filesParsed;
    private final Counter nativeFallback;
    private final Counter entitiesExtracted;

    public AstMetricsService(MeterRegistry registry) {
        this.parseTimer = Timer.builder("review.ast.parse")
                .description("AST preprocessing duration (tree-sitter native parse per diff)")
                .publishPercentiles(0.5, 0.95, 0.99)
                .register(registry);
        this.diffBytes = DistributionSummary.builder("review.ast.diff.bytes")
                .description("Diff payload size fed into AST preprocessing")
                .baseUnit("bytes")
                .publishPercentiles(0.5, 0.95)
                .register(registry);
        this.filesParsed = Counter.builder("review.ast.files.parsed")
                .description("Diff files parsed via the tree-sitter native parser")
                .register(registry);
        this.nativeFallback = Counter.builder("review.ast.native.fallback")
                .description("Diff files that fell back to regex parsing after native parse failure")
                .register(registry);
        this.entitiesExtracted = Counter.builder("review.ast.entities.extracted")
                .description("AST entities extracted by the native parse path")
                .register(registry);
    }

    /** 记录一次完整预处理：diff 载荷入 summary，耗时入 Timer。 */
    public AstPreprocessedResult recordPreprocess(String diffContent, Supplier<AstPreprocessedResult> action) {
        diffBytes.record(diffContent == null ? 0 : diffContent.length());
        return parseTimer.record(action);
    }

    /** 记录一个走 tree-sitter 原生路径并成功产出实体的文件。 */
    public void recordNativeParsed(int entityCount) {
        filesParsed.increment();
        if (entityCount > 0) {
            entitiesExtracted.increment(entityCount);
        }
    }

    /** 记录一个原生解析失败/无实体、回退正则路径的文件。 */
    public void recordNativeFallback() {
        nativeFallback.increment();
    }
}
