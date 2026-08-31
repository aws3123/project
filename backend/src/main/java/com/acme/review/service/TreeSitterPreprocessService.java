package com.acme.review.service;

import com.acme.review.ast.AstEntity;
import com.acme.review.ast.AstPreprocessedResult;
import com.acme.review.ast.AstRelation;
import com.acme.review.ast.TreeSitterLanguage;
import com.acme.review.ast.TreeSitterNativeParser;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

@Service
public class TreeSitterPreprocessService {

    private static final Logger log = LoggerFactory.getLogger(TreeSitterPreprocessService.class);

    private final TreeSitterNativeParser nativeParser;

    public TreeSitterPreprocessService(TreeSitterNativeParser nativeParser) {
        this.nativeParser = nativeParser;
    }

    private static final Pattern DIFF_HUNK_PATTERN = Pattern.compile(
            "@@ -\\d+(?:,\\d+)? \\+(\\d+)(?:,(\\d+)?)? @@");

    private static final Pattern[] JAVA_PATTERNS = {
            Pattern.compile("(?:public|private|protected)?\\s*(?:static)?\\s*(?:final)?\\s*(?:synchronized)?\\s*[\\w<>\\[\\],\\s]+\\s+(\\w+)\\s*\\([^)]*\\)\\s*(?:throws\\s+[\\w.,\\s]+)?\\s*\\{"),
            Pattern.compile("(?:public|private|protected)?\\s*(?:static)?\\s*(?:final)?\\s*class\\s+(\\w+)"),
            Pattern.compile("(?:public|private|protected)?\\s*(?:static)?\\s*(?:final)?\\s*interface\\s+(\\w+)"),
            Pattern.compile("import\\s+([\\w.]+);"),
            Pattern.compile("(?:public|private|protected)?\\s*(?:static)?\\s*(?:final)?\\s*[\\w<>\\[\\],]+\\s+(\\w+)\\s*[=;]"),
    };

    private static final Pattern[] PYTHON_PATTERNS = {
            Pattern.compile("def\\s+(\\w+)\\s*\\("),
            Pattern.compile("class\\s+(\\w+)[\\(:]"),
            Pattern.compile("(?:from\\s+([\\w.]+)\\s+)?import\\s+([\\w.,\\s]+)"),
            Pattern.compile("async\\s+def\\s+(\\w+)\\s*\\("),
    };

    private static final Pattern[] TS_PATTERNS = {
            Pattern.compile("(?:export\\s+)?(?:async\\s+)?function\\s+(\\w+)\\s*[\\(<]"),
            Pattern.compile("(?:export\\s+)?(?:abstract\\s+)?class\\s+(\\w+)"),
            Pattern.compile("(?:export\\s+)?interface\\s+(\\w+)"),
            Pattern.compile("(?:export\\s+)?const\\s+(\\w+)\\s*=\\s*(?:async\\s*)?\\([^)]*\\)\\s*=>"),
            Pattern.compile("import\\s+\\{[^}]+\\}\\s+from\\s+['\"]([^'\"]+)['\"]"),
            Pattern.compile("import\\s+(\\w+)\\s+from\\s+['\"]([^'\"]+)['\"]"),
            Pattern.compile("(\\w+)\\s*:\\s*(?:private|public|protected)?\\s*(?:async\\s*)?(\\w+)\\s*\\([^)]*\\)\\s*[:;]"),
    };

    private static final Pattern[] SQL_PATTERNS = {
            Pattern.compile("(?i)CREATE\\s+TABLE\\s+(?:IF\\s+NOT\\s+EXISTS\\s+)?(\\w+)"),
            Pattern.compile("(?i)ALTER\\s+TABLE\\s+(\\w+)"),
            Pattern.compile("(?i)DROP\\s+TABLE\\s+(?:IF\\s+EXISTS\\s+)?(\\w+)"),
            Pattern.compile("(?i)CREATE\\s+(?:UNIQUE\\s+)?INDEX\\s+(?:IF\\s+NOT\\s+EXISTS\\s+)?(\\w+)"),
    };

    private static final Pattern METHOD_CALL_PATTERN = Pattern.compile(
            "(?:\\w+\\.)?(\\w+)\\s*\\(");

    private static final Pattern EXTENDS_PATTERN = Pattern.compile(
            "(?:class\\s+\\w+\\s+)?extends\\s+(\\w+)");

    private static final Pattern IMPLEMENTS_PATTERN = Pattern.compile(
            "implements\\s+([\\w.,\\s]+)");

    public AstPreprocessedResult preprocess(String diffContent) {
        List<SourceFileInput> files = splitDiffIntoFiles(diffContent);
        return preprocessFiles(files);
    }

    public AstPreprocessedResult preprocessFiles(List<SourceFileInput> files) {
        boolean allNativeOk = true;
        List<AstEntity> allEntities = new ArrayList<>();
        List<AstRelation> allRelations = new ArrayList<>();
        Set<String> detectedLanguages = new LinkedHashSet<>();

        for (SourceFileInput file : files) {
            TreeSitterLanguage lang = TreeSitterLanguage.fromExtension(file.getPath());
            if (lang != null) {
                detectedLanguages.add(lang.getLanguageId());
            }

            AstPreprocessedResult nativeResult = null;
            if (lang != null) {
                try {
                    String reconstructed = reconstructSourceFromDiff(file.getDiff());
                    Set<Integer> changedLines = extractChangedLines(file.getDiff());
                    nativeResult = nativeParser.parseWithChangedLines(
                            reconstructed, lang, file.getPath(), changedLines);
                } catch (Exception e) {
                    log.debug("Native parse failed in preprocessFiles for {}: {}", file.getPath(), e.getMessage());
                }
            }

            if (nativeResult != null && !nativeResult.getEntities().isEmpty()) {
                allEntities.addAll(nativeResult.getEntities());
                allRelations.addAll(nativeResult.getRelations());
            } else {
                allNativeOk = false;
            }
        }

        if (allNativeOk && !allEntities.isEmpty()) {
            AstPreprocessedResult result = new AstPreprocessedResult();
            result.setEntities(allEntities);
            result.setRelations(deduplicateRelations(allRelations));
            result.setFileCount(files.size());
            result.setDetectedLanguages(detectedLanguages);
            return result;
        }

        return originalPreprocessFiles(files);
    }

    private AstPreprocessedResult originalPreprocessFiles(List<SourceFileInput> files) {
        List<AstEntity> allEntities = new ArrayList<>();
        List<AstRelation> allRelations = new ArrayList<>();
        Set<String> detectedLanguages = new LinkedHashSet<>();

        for (SourceFileInput file : files) {
            TreeSitterLanguage lang = TreeSitterLanguage.fromExtension(file.getPath());
            String langName = lang != null ? lang.getLanguageId() : "unknown";
            detectedLanguages.add(langName);

            Set<Integer> changedLines = extractChangedLines(file.getDiff());
            List<AstEntity> fileEntities = parseFile(file.getPath(), file.getDiff(), lang, changedLines);
            List<AstRelation> fileRelations = extractRelations(fileEntities, file.getDiff(), lang);

            allEntities.addAll(fileEntities);
            allRelations.addAll(fileRelations);
        }

        AstPreprocessedResult result = new AstPreprocessedResult();
        result.setEntities(allEntities);
        result.setRelations(deduplicateRelations(allRelations));
        result.setFileCount(files.size());
        result.setDetectedLanguages(detectedLanguages);
        return result;
    }

    List<SourceFileInput> splitDiffIntoFiles(String diffContent) {
        List<SourceFileInput> files = new ArrayList<>();
        Pattern fileHeader = Pattern.compile("^diff --git a/(.+?) b/(.+?)$", Pattern.MULTILINE);
        Matcher m = fileHeader.matcher(diffContent);

        List<Integer> starts = new ArrayList<>();
        List<String> paths = new ArrayList<>();
        while (m.find()) {
            starts.add(m.start());
            paths.add(m.group(2) != null ? m.group(2) : m.group(1));
        }

        for (int i = 0; i < starts.size(); i++) {
            int start = starts.get(i);
            int end = (i + 1 < starts.size()) ? starts.get(i + 1) : diffContent.length();
            String fileDiff = diffContent.substring(start, end).trim();
            if (!fileDiff.isEmpty()) {
                files.add(new SourceFileInput(paths.get(i), fileDiff));
            }
        }

        if (files.isEmpty() && !diffContent.isBlank()) {
            String path = inferVirtualPath(diffContent);
            files.add(new SourceFileInput(path, diffContent));
        }

        return files;
    }

    private String inferVirtualPath(String diffContent) {
        String upper = diffContent.toUpperCase(Locale.ROOT);
        if (upper.contains("SELECT") || upper.contains("INSERT") || upper.contains("CREATE TABLE")) {
            return "changes.sql";
        }
        if (upper.contains("@REQUESTMAPPING") || upper.contains("@GETMAPPING") || upper.contains("@POSTMAPPING")) {
            return "controller.diff";
        }
        if (upper.contains("@SERVICE") || upper.contains("@COMPONENT")) {
            return "service.diff";
        }
        if (upper.contains("DEF ") || upper.contains("IMPORT ") || upper.contains("CLASS ")) {
            return "changes.py";
        }
        if (upper.contains("EXPORT ") || upper.contains("CONST ") || upper.contains("INTERFACE ")) {
            return "changes.ts";
        }
        return "diff.patch";
    }

    Set<Integer> extractChangedLines(String diff) {
        Set<Integer> ranges = new LinkedHashSet<>();
        Matcher m = DIFF_HUNK_PATTERN.matcher(diff);
        while (m.find()) {
            int start = Integer.parseInt(m.group(1));
            String countStr = m.group(2);
            int count = (countStr != null && !countStr.isEmpty()) ? Integer.parseInt(countStr) : 1;
            for (int i = start; i < start + count; i++) {
                ranges.add(i);
            }
        }
        if (ranges.isEmpty()) {
            int lineNum = 0;
            for (String line : diff.split("\\R")) {
                lineNum++;
                if (line.startsWith("+") && !line.startsWith("+++")) {
                    ranges.add(lineNum);
                }
            }
        }
        return ranges;
    }

    /**
     * Reconstruct full source from a unified diff by taking context lines (starting with ' ')
     * and added lines (starting with '+'), skipping removed lines (starting with '-').
     */
    static String reconstructSourceFromDiff(String diff) {
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

    private List<AstEntity> parseFile(String path, String diff, TreeSitterLanguage lang, Set<Integer> changedLines) {
        if (lang == null) {
            return parseGeneric(path, diff, "unknown");
        }
        switch (lang) {
            case JAVA:
                return parseWithPatterns(path, diff, "java", JAVA_PATTERNS, changedLines, new String[]{"method", "class", "interface", "import", "field"});
            case PYTHON:
                return parsePython(path, diff, changedLines);
            case TYPESCRIPT:
            case JAVASCRIPT:
                return parseTypeScript(path, diff, lang.getLanguageId(), changedLines);
            case SQL:
                return parseSql(path, diff, changedLines);
            default:
                return parseGeneric(path, diff, lang.getLanguageId());
        }
    }

    private List<AstEntity> parsePython(String path, String diff, Set<Integer> changedLines) {
        List<AstEntity> entities = new ArrayList<>();
        int lineNum = 0;
        String currentClass = "";
        String packageName = extractPythonPackage(diff);

        for (String line : diff.split("\\R")) {
            lineNum++;
            if (!line.startsWith("+") || line.startsWith("+++")) continue;
            String content = line.substring(1).strip();

            Matcher classM = Pattern.compile("class\\s+(\\w+)[\\(:]").matcher(content);
            if (classM.find()) {
                currentClass = classM.group(1);
                if (changedLines.isEmpty() || changedLines.contains(lineNum)) {
                    AstEntity e = new AstEntity(currentClass, "class", path, lineNum, lineNum, "python");
                    e.setFullyQualifiedName(packageName.isEmpty() ? path + "::" + currentClass : packageName + "." + currentClass);
                    e.setPackageName(packageName);
                    entities.add(e);
                }
                continue;
            }

            Matcher funcM = Pattern.compile("(?:async\\s+)?def\\s+(\\w+)\\s*\\(").matcher(content);
            if (funcM.find()) {
                String name = funcM.group(1);
                if (changedLines.isEmpty() || changedLines.contains(lineNum)) {
                    AstEntity e = new AstEntity(name, "method", path, lineNum, lineNum, "python");
                    String fqn = path + "::" + name;
                    if (!currentClass.isEmpty()) {
                        fqn = (packageName.isEmpty() ? "" : packageName + ".") + currentClass + "." + name;
                    } else if (!packageName.isEmpty()) {
                        fqn = packageName + "." + name;
                    }
                    e.setFullyQualifiedName(fqn);
                    e.setParentClass(currentClass);
                    e.setPackageName(packageName);
                    e.setSignature(content);
                    entities.add(e);
                }
                continue;
            }

            Matcher importM = Pattern.compile("(?:from\\s+([\\w.]+)\\s+)?import\\s+([\\w.,\\s]+)").matcher(content);
            if (importM.find() && (changedLines.isEmpty() || changedLines.contains(lineNum))) {
                String imported = importM.group(2) != null ? importM.group(2).strip() : content;
                AstEntity e = new AstEntity(imported, "import", path, lineNum, lineNum, "python");
                e.setSignature(content);
                entities.add(e);
            }
        }
        return entities;
    }

    private String extractPythonPackage(String diff) {
        for (String line : diff.split("\\R")) {
            if (line.startsWith("+") && !line.startsWith("+++")) {
                Matcher m = Pattern.compile("^from\\s+([\\w.]+)\\s+import").matcher(line.substring(1).strip());
                if (m.find()) return m.group(1);
            }
        }
        return "";
    }

    private List<AstEntity> parseTypeScript(String path, String diff, String language, Set<Integer> changedLines) {
        List<AstEntity> entities = new ArrayList<>();
        int lineNum = 0;
        String currentClass = "";

        for (String line : diff.split("\\R")) {
            lineNum++;
            if (!line.startsWith("+") || line.startsWith("+++")) continue;
            String content = line.substring(1).strip();

            Matcher classM = Pattern.compile("(?:export\\s+)?(?:abstract\\s+)?class\\s+(\\w+)").matcher(content);
            if (classM.find()) {
                currentClass = classM.group(1);
                if (changedLines.isEmpty() || changedLines.contains(lineNum)) {
                    AstEntity e = new AstEntity(currentClass, "class", path, lineNum, lineNum, language);
                    e.setFullyQualifiedName(path + "::" + currentClass);
                    entities.add(e);
                }
                continue;
            }

            Matcher funcM = Pattern.compile("(?:export\\s+)?(?:async\\s+)?function\\s+(\\w+)\\s*[\\(<]").matcher(content);
            if (funcM.find()) {
                String name = funcM.group(1);
                if (changedLines.isEmpty() || changedLines.contains(lineNum)) {
                    AstEntity e = new AstEntity(name, "method", path, lineNum, lineNum, language);
                    e.setFullyQualifiedName(path + "::" + name);
                    e.setSignature(content);
                    entities.add(e);
                }
                continue;
            }

            Matcher arrowM = Pattern.compile("(?:export\\s+)?const\\s+(\\w+)\\s*=\\s*(?:async\\s*)?\\([^)]*\\)\\s*=>").matcher(content);
            if (arrowM.find()) {
                String name = arrowM.group(1);
                if (changedLines.isEmpty() || changedLines.contains(lineNum)) {
                    AstEntity e = new AstEntity(name, "method", path, lineNum, lineNum, language);
                    e.setFullyQualifiedName(path + "::" + name);
                    e.setSignature(content);
                    entities.add(e);
                }
                continue;
            }

            Matcher methodM = Pattern.compile("(\\w+)\\s*\\([^)]*\\)\\s*:\\s*\\w+\\s*\\{").matcher(content);
            if (methodM.find() && !currentClass.isEmpty()) {
                String name = methodM.group(1);
                if (changedLines.isEmpty() || changedLines.contains(lineNum)) {
                    AstEntity e = new AstEntity(name, "method", path, lineNum, lineNum, language);
                    e.setFullyQualifiedName(path + "::" + currentClass + "::" + name);
                    e.setParentClass(currentClass);
                    e.setSignature(content);
                    entities.add(e);
                }
                continue;
            }

            Matcher importM = Pattern.compile("import\\s+\\{[^}]+\\}\\s+from\\s+['\"]([^'\"]+)['\"]").matcher(content);
            if (!importM.find()) {
                importM = Pattern.compile("import\\s+(\\w+)\\s+from\\s+['\"]([^'\"]+)['\"]").matcher(content);
            }
            if (importM.find() && (changedLines.isEmpty() || changedLines.contains(lineNum))) {
                AstEntity e = new AstEntity(importM.group(1), "import", path, lineNum, lineNum, language);
                e.setSignature(content);
                entities.add(e);
            }
        }
        return entities;
    }

    private List<AstEntity> parseSql(String path, String diff, Set<Integer> changedLines) {
        List<AstEntity> entities = new ArrayList<>();
        int lineNum = 0;

        for (String line : diff.split("\\R")) {
            lineNum++;
            if (!line.startsWith("+") || line.startsWith("+++")) continue;
            if (!changedLines.isEmpty() && !changedLines.contains(lineNum)) continue;
            String content = line.substring(1).strip();

            for (int i = 0; i < SQL_PATTERNS.length; i++) {
                Matcher m = SQL_PATTERNS[i].matcher(content);
                if (m.find()) {
                    String kind = i == 3 ? "index" : "table";
                    AstEntity e = new AstEntity(m.group(1), kind, path, lineNum, lineNum, "sql");
                    e.setFullyQualifiedName(path + "::" + m.group(1));
                    e.setSignature(content.length() > 120 ? content.substring(0, 120) : content);
                    entities.add(e);
                    break;
                }
            }
        }
        return entities;
    }

    private List<AstEntity> parseWithPatterns(String path, String diff, String language, Pattern[] patterns, Set<Integer> changedLines, String[] kinds) {
        List<AstEntity> entities = new ArrayList<>();
        int lineNum = 0;
        String currentClass = "";

        for (String line : diff.split("\\R")) {
            lineNum++;
            if (!line.startsWith("+") || line.startsWith("+++")) continue;
            if (!changedLines.isEmpty() && !changedLines.contains(lineNum)) continue;
            String content = line.substring(1).strip();

            for (int i = 0; i < patterns.length; i++) {
                Matcher m = patterns[i].matcher(content);
                if (m.find()) {
                    String name = m.group(1);
                    String kind = i < kinds.length ? kinds[i] : "unknown";
                    if (name == null || name.isEmpty()) continue;

                    AstEntity e = new AstEntity(name, kind, path, lineNum, lineNum, language);
                    if ("class".equals(kind) || "interface".equals(kind)) {
                        currentClass = name;
                        e.setFullyQualifiedName(path + "::" + name);
                    } else if ("method".equals(kind)) {
                        e.setFullyQualifiedName(currentClass.isEmpty() ? path + "::" + name : path + "::" + currentClass + "::" + name);
                        e.setParentClass(currentClass);
                        e.setSignature(content);
                    } else {
                        e.setFullyQualifiedName(path + "::" + name);
                        e.setSignature(content);
                    }
                    entities.add(e);
                    break;
                }
            }
        }
        return entities;
    }

    private List<AstEntity> parseGeneric(String path, String diff, String language) {
        List<AstEntity> entities = new ArrayList<>();
        int lineNum = 0;

        Pattern[] genericPatterns = {
                Pattern.compile("(?:public|private|protected)?\\s*(?:static)?\\s*\\w+\\s+(\\w+)\\s*\\("),
                Pattern.compile("def\\s+(\\w+)\\s*\\("),
                Pattern.compile("class\\s+(\\w+)"),
                Pattern.compile("function\\s+(\\w+)\\s*\\("),
                Pattern.compile("(?:export\\s+)?const\\s+(\\w+)\\s*="),
        };
        String[] genericKinds = {"method", "method", "class", "method", "method"};

        for (String line : diff.split("\\R")) {
            lineNum++;
            if (!line.startsWith("+") || line.startsWith("+++")) continue;
            String content = line.substring(1).strip();

            for (int i = 0; i < genericPatterns.length; i++) {
                Matcher m = genericPatterns[i].matcher(content);
                if (m.find()) {
                    AstEntity e = new AstEntity(m.group(1), genericKinds[i], path, lineNum, lineNum, language);
                    e.setFullyQualifiedName(path + "::" + m.group(1));
                    e.setSignature(content);
                    entities.add(e);
                    break;
                }
            }
        }
        return entities;
    }

    private List<AstRelation> extractRelations(List<AstEntity> entities, String diff, TreeSitterLanguage lang) {
        List<AstRelation> relations = new ArrayList<>();
        Set<String> qnames = new LinkedHashSet<>();
        for (AstEntity e : entities) {
            if (e.getFullyQualifiedName() != null) {
                qnames.add(e.getFullyQualifiedName());
            }
        }

        for (String line : diff.split("\\R")) {
            if (!line.startsWith("+") || line.startsWith("+++")) continue;
            String content = line.substring(1).strip();

            Matcher callM = METHOD_CALL_PATTERN.matcher(content);
            while (callM.find()) {
                String called = callM.group(1);
                for (AstEntity e : entities) {
                    if ("method".equals(e.getKind()) && called.equals(e.getName()) && e.getFullyQualifiedName() != null) {
                        AstEntity enclosing = findEnclosingEntity(entities, e.getLineStart());
                        if (enclosing != null && enclosing.getFullyQualifiedName() != null) {
                            relations.add(new AstRelation(enclosing.getFullyQualifiedName(), e.getFullyQualifiedName(), "CALLS"));
                        }
                    }
                }
            }

            Matcher extendsM = EXTENDS_PATTERN.matcher(content);
            if (extendsM.find()) {
                for (AstEntity e : entities) {
                    if (e.getName().equals(extendsM.group(1)) && "class".equals(e.getKind())) {
                        for (AstEntity src : entities) {
                            if ("class".equals(src.getKind()) && src.getLineStart() != e.getLineStart()) {
                                relations.add(new AstRelation(
                                        src.getFullyQualifiedName(), e.getFullyQualifiedName(), "EXTENDS"));
                                break;
                            }
                        }
                    }
                }
            }
        }
        return relations;
    }

    private AstEntity findEnclosingEntity(List<AstEntity> entities, int line) {
        for (AstEntity e : entities) {
            if ("method".equals(e.getKind()) && e.getLineStart() <= line && line <= (e.getLineEnd() > 0 ? e.getLineEnd() : e.getLineStart() + 10)) {
                return e;
            }
        }
        for (AstEntity e : entities) {
            if ("class".equals(e.getKind()) && e.getLineStart() <= line) {
                return e;
            }
        }
        return entities.isEmpty() ? null : entities.get(0);
    }

    private List<AstRelation> deduplicateRelations(List<AstRelation> relations) {
        Set<String> seen = new LinkedHashSet<>();
        List<AstRelation> deduplicated = new ArrayList<>();
        for (AstRelation r : relations) {
            String key = r.getSource() + "->" + r.getTarget() + "#" + r.getRelationType();
            if (seen.add(key)) {
                deduplicated.add(r);
            }
        }
        return deduplicated;
    }

    public static class SourceFileInput {
        private final String path;
        private final String diff;

        public SourceFileInput(String path, String diff) {
            this.path = path;
            this.diff = diff;
        }

        public String getPath() { return path; }
        public String getDiff() { return diff; }
    }
}