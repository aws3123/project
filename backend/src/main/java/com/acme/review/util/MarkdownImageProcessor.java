package com.acme.review.util;

import com.acme.review.dto.ReviewSyncResponse;

import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Processes markdown image syntax in review responses, replacing placeholder URLs
 * with actual MinIO-accessible URLs before sending to the frontend.
 */
public final class MarkdownImageProcessor {

    private static final Pattern IMAGE_MD_PATTERN =
            Pattern.compile("(!\\[([^\\]]*)]\\(([^)]+)\\))");
    private static final String PLACEHOLDER_PREFIX = "PLACEHOLDER:";

    private MarkdownImageProcessor() {
    }

    /**
     * Replace PLACEHOLDER: paths in markdown image syntax with MinIO public URLs.
     *
     * Input:  ![desc](PLACEHOLDER:incident-001/arch.png)
     * Output: ![desc](http://minio:9000/incident-images/images/incident-001/arch.png)
     */
    public static String replaceImageUrls(String text, String minioEndpoint, String bucket) {
        if (text == null || text.isEmpty() || !text.contains(PLACEHOLDER_PREFIX)) {
            return text;
        }

        String endpoint = minioEndpoint != null ? minioEndpoint.replaceAll("/+$", "") : "";

        Matcher matcher = IMAGE_MD_PATTERN.matcher(text);
        StringBuilder sb = new StringBuilder();
        while (matcher.find()) {
            String fullMatch = matcher.group(1);
            String altText = matcher.group(2);
            String url = matcher.group(3);

            if (url.startsWith(PLACEHOLDER_PREFIX)) {
                String relative = url.substring(PLACEHOLDER_PREFIX.length());
                String resolved = endpoint + "/" + bucket + "/images/" + relative;
                matcher.appendReplacement(sb, Matcher.quoteReplacement(
                        "![" + (altText != null ? altText : "") + "](" + resolved + ")"));
            } else {
                matcher.appendReplacement(sb, Matcher.quoteReplacement(fullMatch));
            }
        }
        matcher.appendTail(sb);
        return sb.toString();
    }

    /**
     * Process all text fields in a ReviewSyncResponse, replacing placeholder image URLs.
     */
    public static ReviewSyncResponse processImages(
            ReviewSyncResponse response, String minioEndpoint, String bucket) {
        if (response == null) {
            return null;
        }

        if (response.getRiskSummary() != null) {
            response.setRiskSummary(
                    replaceImageUrls(response.getRiskSummary(), minioEndpoint, bucket));
        }

        if (response.getDetails() != null) {
            List<String> processed = new ArrayList<>(response.getDetails().size());
            for (String detail : response.getDetails()) {
                processed.add(replaceImageUrls(detail, minioEndpoint, bucket));
            }
            response.setDetails(processed);
        }

        return response;
    }
}
