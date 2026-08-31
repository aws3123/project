package com.acme.review.service;

import com.acme.review.ast.AstEntity;
import com.acme.review.ast.AstPreprocessedResult;
import com.acme.review.ast.AstRelation;
import com.acme.review.ast.TreeSitterLanguage;
import com.acme.review.ast.TreeSitterNativeParser;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.util.*;
import java.util.stream.Collectors;

@Service
public class ReviewContextPreprocessService {

    private static final Logger log = LoggerFactory.getLogger(ReviewContextPreprocessService.class);

    private final TreeSitterNativeParser nativeParser;

    public ReviewContextPreprocessService(TreeSitterNativeParser nativeParser) {
        this.nativeParser = nativeParser;
    }

    public Map<String, Object> extractContext(String diffContent) {
        TreeSitterPreprocessService.SourceFileInput[] files = splitDiffFiles(diffContent);

        List<Map<String, Object>> callGraph = new ArrayList<>();
        Set<String> allAnnotations = new LinkedHashSet<>();
        Set<String> allImports = new LinkedHashSet<>();
        List<Map<String, Object>> riskSignals = new ArrayList<>();
        List<Map<String, Object>> fileContexts = new ArrayList<>();

        for (TreeSitterPreprocessService.SourceFileInput file : files) {
            TreeSitterLanguage lang = TreeSitterLanguage.fromExtension(file.getPath());
            if (lang == null) continue;

            String reconstructed = reconstructSource(file.getDiff());
            Set<Integer> changedLines = extractChangedLines(file.getDiff());

            AstPreprocessedResult parsed;
            try {
                parsed = nativeParser.parseWithChangedLines(reconstructed, lang, file.getPath(), changedLines);
            } catch (Exception e) {
                log.debug("Native parse failed for context extraction: {} {}", file.getPath(), e.getMessage());
                continue;
            }

            if (parsed.getEntities().isEmpty()) continue;

            for (AstEntity entity : parsed.getEntities()) {
                if (entity.getModifiers() != null) {
                    allAnnotations.addAll(entity.getModifiers());
                }
                if ("import".equals(entity.getKind())) {
                    allImports.add(entity.getName());
                }
            }

            for (AstRelation rel : parsed.getRelations()) {
                if ("CALLS".equals(rel.getRelationType())) {
                    Map<String, Object> edge = new LinkedHashMap<>();
                    edge.put("source", rel.getSource());
                    edge.put("target", rel.getTarget());
                    edge.put("file", file.getPath());
                    callGraph.add(edge);
                }
            }

            for (AstEntity entity : parsed.getEntities()) {
                if ("method".equals(entity.getKind())) {
                    List<String> sigs = entity.getModifiers();
                    if (sigs != null) {
                        boolean isTransactional = sigs.stream().anyMatch(
                                m -> m.equalsIgnoreCase("transactional"));
                        if (isTransactional) {
                            riskSignals.add(Map.of(
                                    "type", "TRANSACTIONAL_METHOD",
                                    "method", entity.getFullyQualifiedName(),
                                    "file", file.getPath(),
                                    "line", entity.getLineStart()
                            ));
                        }
                    }
                }
            }

            fileContexts.add(Map.of(
                    "path", file.getPath(),
                    "language", lang.getLanguageId(),
                    "entities", parsed.getEntities().size(),
                    "relations", parsed.getRelations().size()
            ));
        }

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("fileContexts", fileContexts);
        result.put("callGraph", callGraph);
        result.put("annotations", List.copyOf(allAnnotations));
        result.put("imports", List.copyOf(allImports));
        result.put("riskSignals", riskSignals);
        result.put("totalFiles", files.length);
        return result;
    }

    private TreeSitterPreprocessService.SourceFileInput[] splitDiffFiles(String diff) {
        List<TreeSitterPreprocessService.SourceFileInput> files = new ArrayList<>();
        java.util.regex.Pattern fileHeader = java.util.regex.Pattern.compile(
                "^diff --git a/(.+?) b/(.+?)$", java.util.regex.Pattern.MULTILINE);
        java.util.regex.Matcher m = fileHeader.matcher(diff);

        List<Integer> starts = new ArrayList<>();
        List<String> paths = new ArrayList<>();
        while (m.find()) {
            starts.add(m.start());
            paths.add(m.group(2) != null ? m.group(2) : m.group(1));
        }

        for (int i = 0; i < starts.size(); i++) {
            int start = starts.get(i);
            int end = (i + 1 < starts.size()) ? starts.get(i + 1) : diff.length();
            String fileDiff = diff.substring(start, end).trim();
            if (!fileDiff.isEmpty()) {
                files.add(new TreeSitterPreprocessService.SourceFileInput(paths.get(i), fileDiff));
            }
        }
        return files.toArray(new TreeSitterPreprocessService.SourceFileInput[0]);
    }

    private String reconstructSource(String diff) {
        StringBuilder sb = new StringBuilder();
        for (String line : diff.split("\\R")) {
            if (line.startsWith("+++") || line.startsWith("---") || line.startsWith("@@")) continue;
            if (line.startsWith("+")) {
                sb.append(line.substring(1)).append('\n');
            } else if (line.startsWith(" ")) {
                sb.append(line.substring(1)).append('\n');
            }
        }
        return sb.toString();
    }

    private Set<Integer> extractChangedLines(String diff) {
        Set<Integer> lines = new LinkedHashSet<>();
        java.util.regex.Matcher m = java.util.regex.Pattern.compile(
                "@@ -\\d+(?:,\\d+)? \\+(\\d+)(?:,(\\d+)?)? @@").matcher(diff);
        while (m.find()) {
            int start = Integer.parseInt(m.group(1));
            String countStr = m.group(2);
            int count = (countStr != null && !countStr.isEmpty()) ? Integer.parseInt(countStr) : 1;
            for (int i = start; i < start + count; i++) {
                lines.add(i);
            }
        }
        return lines;
    }
}
