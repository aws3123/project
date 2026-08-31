package com.acme.review.service;

import com.acme.review.dto.BusinessRiskAnalysisHints;
import com.acme.review.dto.BusinessRiskBudgetDecision;
import com.acme.review.dto.BusinessRiskLineMap;
import com.acme.review.dto.BusinessRiskPreparedCallEdge;
import com.acme.review.dto.BusinessRiskPreparedHotspot;
import com.acme.review.dto.BusinessRiskPreparedMethod;
import com.acme.review.dto.BusinessRiskPreparedSourceFile;
import com.acme.review.dto.BusinessRiskPreparedSubmission;
import com.acme.review.dto.BusinessRiskSourceMetadataRequest;
import com.acme.review.dto.BusinessRiskSourcePackage;
import com.acme.review.exception.BusinessRiskPreprocessException;
import com.github.javaparser.StaticJavaParser;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.body.BodyDeclaration;
import com.github.javaparser.ast.body.ClassOrInterfaceDeclaration;
import com.github.javaparser.ast.body.FieldDeclaration;
import com.github.javaparser.ast.body.MethodDeclaration;
import com.github.javaparser.ast.expr.AnnotationExpr;
import com.github.javaparser.ast.expr.MethodCallExpr;
import com.github.javaparser.ast.stmt.SynchronizedStmt;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

@Service
@RequiredArgsConstructor
public class BusinessRiskSourcePreprocessService {

    private final BusinessRiskPayloadBudgetService budgetService;

    @Value("${business-risk.source.max-files:50}")
    private int maxFiles;

    public BusinessRiskPreparedSubmission prepare(BusinessRiskSourceMetadataRequest metadata, List<MultipartFile> files) {
        if (files == null || files.isEmpty()) {
            throw new BusinessRiskPreprocessException("SOURCE_FILE_COUNT_EXCEEDED", "At least one Java source file is required");
        }
        if (files.size() > maxFiles) {
            throw new BusinessRiskPreprocessException("SOURCE_FILE_COUNT_EXCEEDED", "Java source file count exceeds max " + maxFiles);
        }

        BusinessRiskSourcePackage sourcePackage = new BusinessRiskSourcePackage();
        BusinessRiskAnalysisHints analysisHints = new BusinessRiskAnalysisHints();
        Set<String> preprocessFindings = new LinkedHashSet<>();
        Set<String> riskTypes = new LinkedHashSet<>();
        Set<String> focusMethods = new LinkedHashSet<>();
        Set<String> focusCallPaths = new LinkedHashSet<>();
        Set<String> hotspotMethodIds = new LinkedHashSet<>();
        List<BusinessRiskPreparedSourceFile> preparedFiles = new ArrayList<>();
        List<BusinessRiskPreparedCallEdge> callGraph = new ArrayList<>();
        long rawTotalBytes = 0L;

        for (MultipartFile file : files) {
            String originalFilename = file.getOriginalFilename();
            if (originalFilename == null || !originalFilename.toLowerCase(Locale.ROOT).endsWith(".java")) {
                throw new BusinessRiskPreprocessException("SOURCE_LANGUAGE_UNSUPPORTED", "Only .java files are supported");
            }

            String content = readContent(file);
            rawTotalBytes += content.getBytes(StandardCharsets.UTF_8).length;
            preparedFiles.add(parseFile(originalFilename, content, callGraph, preprocessFindings, riskTypes, focusMethods, focusCallPaths, hotspotMethodIds));
        }

        sourcePackage.setFiles(preparedFiles);
        sourcePackage.setFileCount(preparedFiles.size());
        sourcePackage.setCallGraph(deduplicateEdges(callGraph));
        sourcePackage.setPreprocessFindings(new ArrayList<>(preprocessFindings));

        analysisHints.setCandidateRiskTypes(new ArrayList<>(riskTypes));
        analysisHints.setFocusMethods(new ArrayList<>(focusMethods));
        analysisHints.setFocusCallPaths(new ArrayList<>(focusCallPaths));
        analysisHints.setHotspotMethodIds(new ArrayList<>(hotspotMethodIds));

        BusinessRiskBudgetDecision budgetDecision = budgetService.applyBudget(sourcePackage, analysisHints, rawTotalBytes);
        sourcePackage.setBudget(budgetDecision);

        BusinessRiskPreparedSubmission submission = new BusinessRiskPreparedSubmission();
        submission.setSourcePackage(sourcePackage);
        submission.setAnalysisHints(analysisHints);
        submission.setRawTotalBytes(rawTotalBytes);
        submission.setPreparedTotalBytes(budgetDecision.getPreparedTotalBytes());
        return submission;
    }

    private BusinessRiskPreparedSourceFile parseFile(
            String path,
            String content,
            List<BusinessRiskPreparedCallEdge> callGraph,
            Set<String> preprocessFindings,
            Set<String> riskTypes,
            Set<String> focusMethods,
            Set<String> focusCallPaths,
            Set<String> hotspotMethodIds
    ) {
        try {
            CompilationUnit compilationUnit = StaticJavaParser.parse(content);
            BusinessRiskPreparedSourceFile preparedFile = new BusinessRiskPreparedSourceFile();
            preparedFile.setPath(path.replace('\\', '/'));
            preparedFile.setPackageName(compilationUnit.getPackageDeclaration().map(decl -> decl.getNameAsString()).orElse(""));

            ClassOrInterfaceDeclaration primaryType = compilationUnit.findFirst(ClassOrInterfaceDeclaration.class)
                    .orElseThrow(() -> new BusinessRiskPreprocessException("SOURCE_AST_PARSE_FAILED", "No class or interface found in " + path));
            preparedFile.setClassName(primaryType.getNameAsString());
            preparedFile.setClassAnnotations(annotationNames(primaryType.getAnnotations()));
            preparedFile.setInterfaces(resolveInterfaces(primaryType));
            preparedFile.setRepositoryDependencies(resolveDependencies(primaryType, "repository"));
            preparedFile.setExternalDependencies(resolveExternalDependencies(primaryType));

            List<BusinessRiskPreparedMethod> methods = new ArrayList<>();
            List<BusinessRiskPreparedHotspot> hotspots = new ArrayList<>();
            for (MethodDeclaration methodDeclaration : primaryType.getMethods()) {
                BusinessRiskPreparedMethod method = buildMethod(primaryType, methodDeclaration, content);
                methods.add(method);
                focusCallPaths.add(method.getMethodId());
                if (isFocusMethod(method)) {
                    focusMethods.add(method.getMethodId());
                }
                for (String keyCall : method.getKeyCalls()) {
                    BusinessRiskPreparedCallEdge edge = new BusinessRiskPreparedCallEdge();
                    edge.setFrom(method.getMethodId());
                    edge.setTo(keyCall);
                    edge.setEdgeType("METHOD_CALL");
                    callGraph.add(edge);
                }
                BusinessRiskPreparedHotspot hotspot = buildHotspot(method);
                if (hotspot != null) {
                    hotspots.add(hotspot);
                    hotspotMethodIds.add(method.getMethodId());
                    preprocessFindings.addAll(hotspot.getRiskTags());
                    riskTypes.addAll(hotspot.getRiskTags());
                }
            }

            preparedFile.setMethods(methods);
            preparedFile.setHotspots(hotspots);
            return preparedFile;
        } catch (BusinessRiskPreprocessException ex) {
            throw ex;
        } catch (Exception ex) {
            throw new BusinessRiskPreprocessException("SOURCE_AST_PARSE_FAILED", "Failed to parse Java source file: " + path, ex);
        }
    }

    private BusinessRiskPreparedMethod buildMethod(ClassOrInterfaceDeclaration owner, MethodDeclaration methodDeclaration, String content) {
        BusinessRiskPreparedMethod method = new BusinessRiskPreparedMethod();
        int startLine = methodDeclaration.getBegin().map(position -> position.line).orElse(1);
        int endLine = methodDeclaration.getEnd().map(position -> position.line).orElse(startLine);
        String methodId = owner.getNameAsString() + "#" + methodDeclaration.getNameAsString() + ":" + startLine;

        method.setMethodId(methodId);
        method.setSignature(methodDeclaration.getDeclarationAsString(true, true, true));
        method.setAnnotations(annotationNames(methodDeclaration.getAnnotations()));
        method.setLineMap(lineMap(startLine, endLine));
        method.setKeyCalls(resolveKeyCalls(methodDeclaration));
        method.setTransactionBoundary(resolveTransactionBoundary(owner, methodDeclaration));
        method.setLockSemantics(resolveLockSemantics(methodDeclaration));
        method.setSnippet(extractSnippet(content, startLine, endLine));
        return method;
    }

    private BusinessRiskPreparedHotspot buildHotspot(BusinessRiskPreparedMethod method) {
        List<String> riskTags = new ArrayList<>();
        List<String> keyCalls = method.getKeyCalls();
        String normalizedCalls = String.join(" ", keyCalls).toLowerCase(Locale.ROOT);

        if ("TRANSACTIONAL".equalsIgnoreCase(method.getTransactionBoundary()) && hasExternalCall(keyCalls)) {
            riskTags.add("EXTERNAL_CALL_INSIDE_TRANSACTION");
        }
        if (containsAny(normalizedCalls, "find", "get", "count") && containsAny(normalizedCalls, "save", "update", "decrease", "deduct", "reserve")) {
            riskTags.add("CHECK_THEN_ACT_CANDIDATE");
        }
        if (containsAny(normalizedCalls, "cache") && containsAny(normalizedCalls, "repository", "save", "update")) {
            riskTags.add("CACHE_DB_DUAL_WRITE");
        }
        if (method.getLockSemantics() != null && !method.getLockSemantics().isEmpty()) {
            riskTags.add("LOCKING_PRESENT");
        }
        if (containsAny(normalizedCalls, "mq", "producer", "publish", "send") && "TRANSACTIONAL".equalsIgnoreCase(method.getTransactionBoundary())) {
            riskTags.add("MQ_INSIDE_TRANSACTION");
        }
        if (riskTags.isEmpty()) {
            return null;
        }

        BusinessRiskPreparedHotspot hotspot = new BusinessRiskPreparedHotspot();
        hotspot.setMethodId(method.getMethodId());
        hotspot.setReason(riskTags.get(0));
        hotspot.setRiskTags(riskTags);
        hotspot.setLineMap(method.getLineMap());
        hotspot.setSnippet(method.getSnippet());
        return hotspot;
    }

    private List<String> resolveKeyCalls(MethodDeclaration methodDeclaration) {
        LinkedHashSet<String> keyCalls = new LinkedHashSet<>();
        for (MethodCallExpr callExpr : methodDeclaration.findAll(MethodCallExpr.class)) {
            String scope = callExpr.getScope().map(Object::toString).orElse("");
            String callName = scope.isBlank() ? callExpr.getNameAsString() : scope + "." + callExpr.getNameAsString();
            keyCalls.add(callName);
        }
        return new ArrayList<>(keyCalls);
    }

    private List<String> annotationNames(List<AnnotationExpr> annotations) {
        List<String> names = new ArrayList<>();
        for (AnnotationExpr annotation : annotations) {
            names.add(annotation.getNameAsString());
        }
        return names;
    }

    private List<String> resolveInterfaces(ClassOrInterfaceDeclaration declaration) {
        LinkedHashSet<String> interfaces = new LinkedHashSet<>();
        declaration.getImplementedTypes().forEach(type -> interfaces.add(type.getNameAsString()));
        declaration.getExtendedTypes().forEach(type -> interfaces.add(type.getNameAsString()));
        return new ArrayList<>(interfaces);
    }

    private List<String> resolveDependencies(ClassOrInterfaceDeclaration declaration, String keyword) {
        LinkedHashSet<String> dependencies = new LinkedHashSet<>();
        for (FieldDeclaration field : declaration.getFields()) {
            String typeName = field.getCommonType().asString();
            if (typeName.toLowerCase(Locale.ROOT).contains(keyword)) {
                dependencies.add(typeName);
            }
        }
        return new ArrayList<>(dependencies);
    }

    private List<String> resolveExternalDependencies(ClassOrInterfaceDeclaration declaration) {
        LinkedHashSet<String> dependencies = new LinkedHashSet<>();
        for (FieldDeclaration field : declaration.getFields()) {
            String typeName = field.getCommonType().asString();
            String normalized = typeName.toLowerCase(Locale.ROOT);
            if (normalized.contains("client")
                    || normalized.contains("gateway")
                    || normalized.contains("producer")
                    || normalized.contains("template")
                    || normalized.contains("feign")
                    || normalized.contains("rest")) {
                dependencies.add(typeName);
            }
        }
        return new ArrayList<>(dependencies);
    }

    private String resolveTransactionBoundary(ClassOrInterfaceDeclaration owner, MethodDeclaration methodDeclaration) {
        if (hasAnnotation(methodDeclaration, "Transactional") || hasAnnotation(owner, "Transactional")) {
            return "TRANSACTIONAL";
        }
        return "NONE";
    }

    private List<String> resolveLockSemantics(MethodDeclaration methodDeclaration) {
        LinkedHashSet<String> semantics = new LinkedHashSet<>();
        if (methodDeclaration.isSynchronized()) {
            semantics.add("SYNCHRONIZED_METHOD");
        }
        if (!methodDeclaration.findAll(SynchronizedStmt.class).isEmpty()) {
            semantics.add("SYNCHRONIZED_BLOCK");
        }
        for (MethodCallExpr callExpr : methodDeclaration.findAll(MethodCallExpr.class)) {
            String callName = callExpr.getNameAsString().toLowerCase(Locale.ROOT);
            if (callName.contains("lock")) {
                semantics.add("EXPLICIT_LOCK");
            }
            if (callName.contains("selectforupdate") || callName.contains("forupdate")) {
                semantics.add("DB_LOCK");
            }
        }
        return new ArrayList<>(semantics);
    }

    private BusinessRiskLineMap lineMap(int startLine, int endLine) {
        BusinessRiskLineMap lineMap = new BusinessRiskLineMap();
        lineMap.setStartLine(Math.max(1, startLine));
        lineMap.setEndLine(Math.max(startLine, endLine));
        return lineMap;
    }

    private String extractSnippet(String content, int startLine, int endLine) {
        String[] lines = content.split("\\R");
        int from = Math.max(0, startLine - 1);
        int to = Math.min(lines.length, endLine);
        StringBuilder builder = new StringBuilder();
        for (int i = from; i < to; i++) {
            builder.append(lines[i]).append('\n');
            if (builder.length() >= 1200) {
                break;
            }
        }
        return builder.toString().trim();
    }

    private boolean hasAnnotation(BodyDeclaration<?> declaration, String annotationName) {
        return declaration.getAnnotations().stream().anyMatch(annotation -> annotationName.equalsIgnoreCase(annotation.getNameAsString()));
    }

    private boolean isFocusMethod(BusinessRiskPreparedMethod method) {
        if ("TRANSACTIONAL".equalsIgnoreCase(method.getTransactionBoundary())) {
            return true;
        }
        if (method.getLockSemantics() != null && !method.getLockSemantics().isEmpty()) {
            return true;
        }
        return hasExternalCall(method.getKeyCalls());
    }

    private boolean hasExternalCall(List<String> keyCalls) {
        for (String keyCall : keyCalls) {
            String normalized = keyCall.toLowerCase(Locale.ROOT);
            if (normalized.contains("client")
                    || normalized.contains("gateway")
                    || normalized.contains("producer")
                    || normalized.contains("template")
                    || normalized.contains("cache")) {
                return true;
            }
        }
        return false;
    }

    private boolean containsAny(String text, String... candidates) {
        for (String candidate : candidates) {
            if (text.contains(candidate)) {
                return true;
            }
        }
        return false;
    }

    private List<BusinessRiskPreparedCallEdge> deduplicateEdges(List<BusinessRiskPreparedCallEdge> edges) {
        LinkedHashSet<String> seen = new LinkedHashSet<>();
        List<BusinessRiskPreparedCallEdge> deduplicated = new ArrayList<>();
        for (BusinessRiskPreparedCallEdge edge : edges) {
            String key = edge.getFrom() + "->" + edge.getTo() + "#" + edge.getEdgeType();
            if (seen.add(key)) {
                deduplicated.add(edge);
            }
        }
        return deduplicated;
    }

    private String readContent(MultipartFile file) {
        try {
            return new String(file.getBytes(), StandardCharsets.UTF_8);
        } catch (IOException ex) {
            throw new BusinessRiskPreprocessException("SOURCE_PREPROCESS_FAILED", "Failed to read source file: " + file.getOriginalFilename(), ex);
        }
    }
}
