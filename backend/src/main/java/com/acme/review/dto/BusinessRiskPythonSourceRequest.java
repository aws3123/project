package com.acme.review.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Getter
@Setter
@NoArgsConstructor
public class BusinessRiskPythonSourceRequest {

    @JsonProperty("schema_version")
    private String schemaVersion;

    @JsonProperty("java_preprocess_version")
    private String javaPreprocessVersion;

    @JsonProperty("project_id")
    private String projectId;

    private String repo;

    private String branch;

    @JsonProperty("request_id")
    private String requestId;

    @JsonProperty("session_id")
    private String sessionId;

    @JsonProperty("task_id")
    private String taskId;

    @JsonProperty("trace_id")
    private String traceId;

    @JsonProperty("source_package")
    private BusinessRiskSourcePackage sourcePackage;

    @JsonProperty("analysis_hints")
    private BusinessRiskAnalysisHints analysisHints;

    @JsonProperty("source_bundle")
    private SourceBundle sourceBundle;

    private Callback callback;

    @JsonProperty("callback_url")
    private String callbackUrl;

    @JsonProperty("callback_token")
    private String callbackToken;

    @JsonProperty("callback_token_header")
    private String callbackTokenHeader;

    @JsonProperty("callback_signature_header")
    private String callbackSignatureHeader;

    @JsonProperty("callback_timestamp_header")
    private String callbackTimestampHeader;

    @JsonProperty("callback_nonce_header")
    private String callbackNonceHeader;

    @JsonProperty("memory_context")
    private Map<String, Object> memoryContext = new HashMap<>();

    @JsonProperty("memory_version")
    private String memoryVersion;

    public static BusinessRiskPythonSourceRequest from(
            BusinessRiskSourceMetadataRequest metadata,
            BusinessRiskPreparedSubmission preparedSubmission,
            String javaPreprocessVersion,
            String taskId,
            String sessionId,
            String traceId,
            String callbackUrl,
            String callbackTokenHeader,
            String callbackToken,
            String callbackSignatureHeader,
            String callbackTimestampHeader,
            String callbackNonceHeader
    ) {
        BusinessRiskPythonSourceRequest target = new BusinessRiskPythonSourceRequest();
        target.setSchemaVersion(metadata.getSchemaVersion());
        target.setJavaPreprocessVersion(javaPreprocessVersion);
        target.setProjectId(metadata.getProjectId());
        target.setRepo(metadata.getRepo());
        target.setBranch(metadata.getBranch());
        target.setRequestId(metadata.getRequestId() != null && !metadata.getRequestId().isBlank() ? metadata.getRequestId() : taskId);
        target.setSessionId(sessionId);
        target.setTaskId(taskId);
        target.setTraceId(traceId);
        target.setMemoryContext(metadata.getMemoryContext() != null ? metadata.getMemoryContext() : new HashMap<>());
        target.setMemoryVersion(metadata.getMemoryVersion());
        target.setSourcePackage(preparedSubmission.getSourcePackage());
        target.setAnalysisHints(preparedSubmission.getAnalysisHints());
        target.setSourceBundle(SourceBundle.from(preparedSubmission.getSourcePackage()));
        target.setCallback(Callback.from(callbackUrl, callbackTokenHeader, callbackSignatureHeader, callbackTimestampHeader, callbackNonceHeader));
        target.setCallbackUrl(callbackUrl);
        target.setCallbackTokenHeader(callbackTokenHeader);
        target.setCallbackToken(callbackToken);
        target.setCallbackSignatureHeader(callbackSignatureHeader);
        target.setCallbackTimestampHeader(callbackTimestampHeader);
        target.setCallbackNonceHeader(callbackNonceHeader);
        return target;
    }

    @Getter
    @Setter
    @NoArgsConstructor
    public static class Callback {

        private String url;

        @JsonProperty("token_header")
        private String tokenHeader;

        @JsonProperty("signature_header")
        private String signatureHeader;

        @JsonProperty("timestamp_header")
        private String timestampHeader;

        @JsonProperty("nonce_header")
        private String nonceHeader;

        static Callback from(
                String callbackUrl,
                String callbackTokenHeader,
                String callbackSignatureHeader,
                String callbackTimestampHeader,
                String callbackNonceHeader
        ) {
            Callback callback = new Callback();
            callback.setUrl(callbackUrl);
            callback.setTokenHeader(callbackTokenHeader);
            callback.setSignatureHeader(callbackSignatureHeader);
            callback.setTimestampHeader(callbackTimestampHeader);
            callback.setNonceHeader(callbackNonceHeader);
            return callback;
        }
    }

    @Getter
    @Setter
    @NoArgsConstructor
    public static class SourceBundle {

        @JsonProperty("file_count")
        private int fileCount;

        private List<SourceFile> files = new ArrayList<>();

        static SourceBundle from(BusinessRiskSourcePackage sourcePackage) {
            SourceBundle target = new SourceBundle();
            if (sourcePackage == null) {
                return target;
            }
            target.setFileCount(sourcePackage.getFileCount());
            if (sourcePackage.getFiles() == null) {
                return target;
            }
            List<SourceFile> mapped = new ArrayList<>(sourcePackage.getFiles().size());
            for (BusinessRiskPreparedSourceFile file : sourcePackage.getFiles()) {
                mapped.add(SourceFile.from(file));
            }
            target.setFiles(mapped);
            return target;
        }
    }

    @Getter
    @Setter
    @NoArgsConstructor
    public static class SourceFile {

        private String path;

        private String language = "java";

        @JsonProperty("class_summary")
        private String classSummary;

        @JsonProperty("method_skeletons")
        private List<MethodSkeleton> methodSkeletons = new ArrayList<>();

        private List<Hotspot> hotspots = new ArrayList<>();

        static SourceFile from(BusinessRiskPreparedSourceFile source) {
            SourceFile target = new SourceFile();
            if (source == null) {
                return target;
            }
            target.setPath(source.getPath());
            target.setClassSummary(source.getClassName());
            if (source.getMethods() != null) {
                List<MethodSkeleton> skeletons = new ArrayList<>(source.getMethods().size());
                for (BusinessRiskPreparedMethod method : source.getMethods()) {
                    skeletons.add(MethodSkeleton.from(method));
                }
                target.setMethodSkeletons(skeletons);
            }
            if (source.getHotspots() != null) {
                List<Hotspot> mappedHotspots = new ArrayList<>(source.getHotspots().size());
                for (BusinessRiskPreparedHotspot hotspot : source.getHotspots()) {
                    mappedHotspots.add(Hotspot.from(hotspot));
                }
                target.setHotspots(mappedHotspots);
            }
            return target;
        }
    }

    @Getter
    @Setter
    @NoArgsConstructor
    public static class MethodSkeleton {

        @JsonProperty("method_id")
        private String methodId;

        private String signature;

        @JsonProperty("control_flow_summary")
        private List<String> controlFlowSummary = new ArrayList<>();

        @JsonProperty("key_calls")
        private List<String> keyCalls = new ArrayList<>();

        @JsonProperty("line_map")
        private LineMap lineMap;

        static MethodSkeleton from(BusinessRiskPreparedMethod source) {
            MethodSkeleton target = new MethodSkeleton();
            if (source == null) {
                return target;
            }
            target.setMethodId(source.getMethodId());
            target.setSignature(source.getSignature());
            List<String> flow = new ArrayList<>();
            if (source.getTransactionBoundary() != null && !source.getTransactionBoundary().isBlank()) {
                flow.add("transaction=" + source.getTransactionBoundary());
            }
            if (source.getLockSemantics() != null && !source.getLockSemantics().isEmpty()) {
                flow.add("lock=" + String.join("|", source.getLockSemantics()));
            }
            target.setControlFlowSummary(flow);
            if (source.getKeyCalls() != null) {
                target.setKeyCalls(new ArrayList<>(source.getKeyCalls()));
            }
            target.setLineMap(LineMap.from(source.getLineMap()));
            return target;
        }
    }

    @Getter
    @Setter
    @NoArgsConstructor
    public static class Hotspot {

        @JsonProperty("method_id")
        private String methodId;

        @JsonProperty("raw_snippet")
        private String rawSnippet;

        private String reason;

        @JsonProperty("line_map")
        private LineMap lineMap;

        static Hotspot from(BusinessRiskPreparedHotspot source) {
            Hotspot target = new Hotspot();
            if (source == null) {
                return target;
            }
            target.setMethodId(source.getMethodId());
            target.setRawSnippet(source.getSnippet());
            target.setReason(source.getReason());
            target.setLineMap(LineMap.from(source.getLineMap()));
            return target;
        }
    }

    @Getter
    @Setter
    @NoArgsConstructor
    public static class LineMap {

        @JsonProperty("start_line")
        private int startLine;

        @JsonProperty("end_line")
        private int endLine;

        static LineMap from(BusinessRiskLineMap source) {
            LineMap target = new LineMap();
            if (source == null) {
                return target;
            }
            target.setStartLine(source.getStartLine());
            target.setEndLine(source.getEndLine());
            return target;
        }
    }
}
