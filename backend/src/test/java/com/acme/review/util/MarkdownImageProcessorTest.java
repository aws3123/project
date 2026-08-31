package com.acme.review.util;

import com.acme.review.dto.ReviewSyncResponse;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

class MarkdownImageProcessorTest {

    private static final String MINIO_ENDPOINT = "http://localhost:9000";
    private static final String BUCKET = "incident-images";

    @Test
    void replaceImageUrls_noPlaceholder_noChange() {
        String input = "纯文本没有图片引用";
        assertEquals(input, MarkdownImageProcessor.replaceImageUrls(input, MINIO_ENDPOINT, BUCKET));
    }

    @Test
    void replaceImageUrls_placeholderReplaced() {
        String input = "如图所示 ![架构图](PLACEHOLDER:incident-001/arch.png)";
        String expected = "如图所示 ![架构图](http://localhost:9000/incident-images/images/incident-001/arch.png)";
        assertEquals(expected, MarkdownImageProcessor.replaceImageUrls(input, MINIO_ENDPOINT, BUCKET));
    }

    @Test
    void replaceImageUrls_multiplePlaceholders() {
        String input = "图1: ![架构](PLACEHOLDER:incident-001/arch.png)\n图2: ![监控](PLACEHOLDER:incident-002/dashboard.jpg)";
        String result = MarkdownImageProcessor.replaceImageUrls(input, MINIO_ENDPOINT, BUCKET);
        assertTrue(result.contains("incident-images/images/incident-001/arch.png"));
        assertTrue(result.contains("incident-images/images/incident-002/dashboard.jpg"));
    }

    @Test
    void replaceImageUrls_externalUrlUnchanged() {
        String input = "外部图片 ![logo](https://example.com/logo.png)";
        assertEquals(input, MarkdownImageProcessor.replaceImageUrls(input, MINIO_ENDPOINT, BUCKET));
    }

    @Test
    void replaceImageUrls_mixedContent() {
        String input = "概要: 此处有风险\n详情: 参考历史事故 ![堆栈](PLACEHOLDER:incident-001/stack.png)\n外部: ![logo](https://example.com/logo.png)";
        String result = MarkdownImageProcessor.replaceImageUrls(input, MINIO_ENDPOINT, BUCKET);
        assertTrue(result.contains("incident-images/images/incident-001/stack.png"));
        assertTrue(result.contains("https://example.com/logo.png"));
    }

    @Test
    void replaceImageUrls_nullAndEmpty() {
        assertNull(MarkdownImageProcessor.replaceImageUrls(null, MINIO_ENDPOINT, BUCKET));
        assertEquals("", MarkdownImageProcessor.replaceImageUrls("", MINIO_ENDPOINT, BUCKET));
    }

    @Test
    void processImages_fullResponse() {
        ReviewSyncResponse response = new ReviewSyncResponse();
        response.setTaskId("test-001");
        response.setRiskScore(75);
        response.setRiskSummary("参考: ![架构图](PLACEHOLDER:incident-001/arch.png)");
        response.setDetails(List.of("详情1", "参考: ![堆栈](PLACEHOLDER:incident-001/stack.png)"));

        MarkdownImageProcessor.processImages(response, MINIO_ENDPOINT, BUCKET);

        assertTrue(response.getRiskSummary().contains("incident-images/images/incident-001/arch.png"));
        assertFalse(response.getRiskSummary().contains("PLACEHOLDER"));
        assertTrue(response.getDetails().get(1).contains("incident-images/images/incident-001/stack.png"));
    }

    @Test
    void processImages_noDetails() {
        ReviewSyncResponse response = new ReviewSyncResponse();
        response.setTaskId("test-002");
        response.setRiskScore(50);
        response.setRiskSummary("无图片");

        MarkdownImageProcessor.processImages(response, MINIO_ENDPOINT, BUCKET);
        assertEquals("无图片", response.getRiskSummary());
        assertNull(response.getDetails());
    }

    @Test
    void processImages_nullResponse() {
        assertNull(MarkdownImageProcessor.processImages(null, MINIO_ENDPOINT, BUCKET));
    }
}
