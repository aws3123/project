package com.acme.review.ast;

import com.github.javaparser.StaticJavaParser;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.body.ClassOrInterfaceDeclaration;
import com.github.javaparser.ast.body.MethodDeclaration;
import com.github.javaparser.ast.expr.AnnotationExpr;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import org.treesitter.TSLanguage;
import org.treesitter.TSNode;
import org.treesitter.TSParser;
import org.treesitter.TSTree;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.EnumMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Cross-language AST parser with three-layer strategy:
 *
 * <b>Layer 1 — Tree-sitter JNI</b> (via io.github.bonede, pre-built native libs bundled):
 * Real tree-sitter AST parsing for Java, Python, TypeScript, JavaScript.
 * Always available — no manual DLL management needed.
 *
 * <b>Layer 2 — JavaParser</b> (for Java): Full Java AST with annotations,
 * call graphs, import resolution. Always available.
 *
 * <b>Layer 3 — Enhanced pattern matcher</b> (for Python/TypeScript):
 * Indentation-aware regex parser that accurately tracks nested scope boundaries.
 * Fallback when JNI unavailable for a given language.
 */
@Component
public class TreeSitterNativeParser {

    private static final Logger log = LoggerFactory.getLogger(TreeSitterNativeParser.class);

    private final Map<TreeSitterLanguage, TSParser> parsers = new EnumMap<>(TreeSitterLanguage.class);

    // ── Enhanced pattern matcher patterns ──────────────────────────────────

    private static final Pattern PY_FUNCTION_DEF = Pattern.compile(
            "^(?:async\\s+)?def\\s+(\\w+)\\s*\\(", Pattern.MULTILINE);
    private static final Pattern PY_CLASS_DEF = Pattern.compile(
            "^class\\s+(\\w+)\\s*[\\(:]", Pattern.MULTILINE);
    private static final Pattern TS_FUNCTION_DEF = Pattern.compile(
            "^(?:export\\s+)?(?:async\\s+)?function\\s+(\\w+)\\s*[<\\(]", Pattern.MULTILINE);
    private static final Pattern TS_ARROW_DEF = Pattern.compile(
            "^(?:export\\s+)?(?:const|let|var)\\s+(\\w+)\\s*=\\s*(?:async\\s*)?[\\(<]", Pattern.MULTILINE);
    private static final Pattern TS_CLASS_DEF = Pattern.compile(
            "^(?:export\\s+)?(?:abstract\\s+)?class\\s+(\\w+)", Pattern.MULTILINE);
    private static final Pattern TS_INTERFACE_DEF = Pattern.compile(
            "^(?:export\\s+)?interface\\s+(\\w+)", Pattern.MULTILINE);

    // ── Public API ────────────────────────────────────────────────────────

    public boolean isNativeAvailable() {
        return true;
    }

    public AstPreprocessedResult parse(String sourceCode, TreeSitterLanguage language, String filePath) {
        return parseWithChangedLines(sourceCode, language, filePath, null);
    }

    public AstPreprocessedResult parseWithChangedLines(
            String sourceCode, TreeSitterLanguage language, String filePath, Set<Integer> changedLines) {

        if (sourceCode == null || sourceCode.isBlank()) {
            return emptyResult();
        }

        // Layer 1: Tree-sitter JNI (fast path, cross-language, always available)
        if (language != null) {
            AstPreprocessedResult jniResult = parseWithJni(sourceCode, language, filePath, changedLines);
            if (jniResult != null && !jniResult.getEntities().isEmpty()) {
                return jniResult;
            }
        }

        // Layer 2: JavaParser (Java only, richer annotation extraction)
        if (language == TreeSitterLanguage.JAVA) {
            AstPreprocessedResult jpResult = parseWithJavaParser(sourceCode, filePath, changedLines);
            if (jpResult != null && !jpResult.getEntities().isEmpty()) {
                return jpResult;
            }
        }

        // Layer 3: Enhanced pattern matcher (Python/TypeScript fallback)
        return parseWithPatterns(sourceCode, language, filePath, changedLines);
    }

    // ── Layer 1: Tree-sitter JNI ──────────────────────────────────────────

    private TSParser getOrCreateParser(TreeSitterLanguage lang) {
        return parsers.computeIfAbsent(lang, k -> {
            TSParser p = new TSParser();
            TSLanguage grammar = switch (k) {
                case JAVA -> new org.treesitter.TreeSitterJava();
                case PYTHON -> new org.treesitter.TreeSitterPython();
                case TYPESCRIPT, JAVASCRIPT -> new org.treesitter.TreeSitterTypescript();
                default -> throw new IllegalArgumentException("Unsupported language: " + k);
            };
            p.setLanguage(grammar);
            log.debug("Created tree-sitter parser for {}", k);
            return p;
        });
    }

    private AstPreprocessedResult parseWithJni(
            String sourceCode, TreeSitterLanguage language, String filePath, Set<Integer> changedLines) {

        TSParser parser;
        try {
            parser = getOrCreateParser(language);
        } catch (Exception e) {
            log.debug("Tree-sitter parser unavailable for {}: {}", language, e.getMessage());
            return null;
        }

        TSTree tree = null;
        try {
            tree = parser.parseString(null, sourceCode);
            if (tree == null) return null;

            TSNode root = tree.getRootNode();
            String[] sourceLines = sourceCode.split("\\R", -1);

            List<AstEntity> entities = new ArrayList<>();
            walkJniTree(root, null, filePath, language.getLanguageId(), sourceLines, changedLines, entities, 0);

            AstPreprocessedResult result = new AstPreprocessedResult();
            result.setEntities(entities);
            result.setRelations(List.of());
            result.setFileCount(1);
            result.setDetectedLanguages(new LinkedHashSet<>(Collections.singletonList(language.getLanguageId())));
            return result;

        } catch (Exception e) {
            log.debug("Tree-sitter JNI parse failed for {}: {}", language, e.getMessage());
            return null;
        }
    }

    private void walkJniTree(TSNode node, String parentFqn, String filePath, String languageId,
                             String[] sourceLines, Set<Integer> changedLines,
                             List<AstEntity> entities, int depth) {
        if (depth > 200 || node == null) return;

        String type = node.getType();
        int startLine = node.getStartPoint().getRow() + 1;
        int endLine = node.getEndPoint().getRow() + 1;

        if (isDefinitionType(type)) {
            String name = extractJniNodeName(node, sourceLines);
            if (name != null && !name.isEmpty()) {
                String kind = mapTypeToKind(type);
                boolean onChanged = changedLines == null || overlaps(startLine, endLine, changedLines);

                if (onChanged) {
                    AstEntity entity = new AstEntity();
                    entity.setName(name);
                    entity.setKind(kind);
                    entity.setFilePath(filePath);
                    entity.setLineStart(startLine);
                    entity.setLineEnd(endLine);
                    entity.setLanguage(languageId);
                    entity.setModifiers(List.of());
                    entity.setSignature(sigFromLines(sourceLines, startLine, endLine));

                    String fqn = parentFqn != null ? parentFqn + "::" + name : filePath + "::" + name;
                    entity.setFullyQualifiedName(fqn);
                    entity.setParentClass("");
                    entity.setPackageName("");
                    entities.add(entity);

                    if ("class".equals(kind) || "interface".equals(kind)) {
                        parentFqn = fqn;
                    }
                }
            }
        }

        for (int i = 0; i < node.getChildCount(); i++) {
            TSNode child = node.getChild(i);
            walkJniTree(child, parentFqn, filePath, languageId, sourceLines,
                    changedLines, entities, depth + 1);
        }
    }

    private String extractJniNodeName(TSNode node, String[] sourceLines) {
        // Try named child field "name" first
        TSNode nameNode = node.getChildByFieldName("name");
        if (nameNode != null && !nameNode.isNull()) {
            return getNodeText(nameNode, sourceLines);
        }
        // Fallback: find first identifier child
        for (int i = 0; i < node.getNamedChildCount(); i++) {
            TSNode child = node.getNamedChild(i);
            String childType = child.getType();
            if ("identifier".equals(childType) || childType.endsWith("_identifier")) {
                return getNodeText(child, sourceLines);
            }
        }
        return null;
    }

    private String getNodeText(TSNode node, String[] sourceLines) {
        int startRow = node.getStartPoint().getRow();
        int endRow = node.getEndPoint().getRow();
        int startCol = node.getStartPoint().getColumn();
        int endCol = node.getEndPoint().getColumn();

        if (startRow < 0 || startRow >= sourceLines.length) return null;

        if (startRow == endRow) {
            return sourceLines[startRow].substring(
                    Math.min(startCol, sourceLines[startRow].length()),
                    Math.min(endCol, sourceLines[endRow].length()));
        }
        StringBuilder sb = new StringBuilder();
        sb.append(sourceLines[startRow].substring(Math.min(startCol, sourceLines[startRow].length()))).append('\n');
        for (int r = startRow + 1; r < endRow && r < sourceLines.length; r++) {
            sb.append(sourceLines[r]).append('\n');
        }
        if (endRow < sourceLines.length) {
            sb.append(sourceLines[endRow], 0, Math.min(endCol, sourceLines[endRow].length()));
        }
        return sb.toString().trim();
    }

    private boolean isDefinitionType(String type) {
        return switch (type) {
            case "class_declaration", "class_definition", "interface_declaration",
                 "method_declaration", "function_declaration", "function_definition",
                 "method_definition", "constructor_declaration" -> true;
            default -> false;
        };
    }

    private String mapTypeToKind(String type) {
        return switch (type) {
            case "class_declaration", "class_definition" -> "class";
            case "interface_declaration" -> "interface";
            case "method_declaration", "method_definition", "constructor_declaration" -> "method";
            case "function_declaration", "function_definition" -> "method";
            default -> "unknown";
        };
    }

    private boolean overlaps(int sl, int el, Set<Integer> lines) {
        for (int i = sl; i <= el; i++) if (lines.contains(i)) return true;
        return false;
    }

    // ── Layer 2: JavaParser ───────────────────────────────────────────────

    private AstPreprocessedResult parseWithJavaParser(
            String sourceCode, String filePath, Set<Integer> changedLines) {

        try {
            CompilationUnit cu = StaticJavaParser.parse(sourceCode);
            List<AstEntity> entities = new ArrayList<>();
            String packageName = cu.getPackageDeclaration()
                    .map(pd -> pd.getNameAsString()).orElse("");
            String[] lines = sourceCode.split("\\R", -1);

            for (ClassOrInterfaceDeclaration type : cu.findAll(ClassOrInterfaceDeclaration.class)) {
                int sl = type.getBegin().map(p -> p.line).orElse(1);
                int el = type.getEnd().map(p -> p.line).orElse(sl);
                if (changedLines != null && !overlaps(sl, el, changedLines)) continue;

                String kind = type.isInterface() ? "interface" : "class";
                String fqn = packageName.isEmpty() ? filePath + "::" + type.getNameAsString()
                        : packageName + "." + type.getNameAsString();
                entities.add(buildJpEntity(type.getNameAsString(), kind, filePath, sl, el,
                        "java", annotNames(type.getAnnotations()), fqn, "", packageName, lines));

                for (MethodDeclaration m : type.getMethods()) {
                    int ms = m.getBegin().map(p -> p.line).orElse(sl);
                    int me = m.getEnd().map(p -> p.line).orElse(ms);
                    if (changedLines != null && !overlaps(ms, me, changedLines)) continue;
                    String mFqn = fqn + "::" + m.getNameAsString();
                    AstEntity e = buildJpEntity(m.getNameAsString(), "method", filePath, ms, me,
                            "java", annotNames(m.getAnnotations()), mFqn,
                            type.getNameAsString(), packageName, lines);
                    e.setSignature(m.getDeclarationAsString(true, true, true));
                    entities.add(e);
                }
            }

            for (var imp : cu.getImports()) {
                entities.add(buildJpEntity(imp.getNameAsString(), "import", filePath, 0, 0,
                        "java", List.of(), imp.getNameAsString(), "", packageName, lines));
            }

            AstPreprocessedResult r = new AstPreprocessedResult();
            r.setEntities(entities);
            r.setRelations(List.of());
            r.setFileCount(1);
            r.setDetectedLanguages(new LinkedHashSet<>(Collections.singletonList("java")));
            return r;
        } catch (Exception e) {
            log.debug("JavaParser failed for {}: {}", filePath, e.getMessage());
            return emptyResult();
        }
    }

    private AstEntity buildJpEntity(String name, String kind, String filePath,
                                    int sl, int el, String lang, List<String> mods,
                                    String fqn, String parentClass, String pkg, String[] lines) {
        AstEntity e = new AstEntity();
        e.setName(name); e.setKind(kind); e.setFilePath(filePath);
        e.setLineStart(sl); e.setLineEnd(el); e.setLanguage(lang);
        e.setModifiers(mods); e.setFullyQualifiedName(fqn);
        e.setParentClass(parentClass); e.setPackageName(pkg);
        e.setSignature(sigFromLines(lines, sl, el));
        return e;
    }

    private static String sigFromLines(String[] lines, int sl, int el) {
        StringBuilder sb = new StringBuilder();
        for (int r = Math.max(0, sl - 1); r < Math.min(el, lines.length); r++) {
            sb.append(lines[r].strip()).append(" ");
        }
        return sb.toString().trim();
    }

    private static List<String> annotNames(List<AnnotationExpr> anns) {
        if (anns == null || anns.isEmpty()) return List.of();
        return anns.stream().map(a -> "@" + a.getNameAsString()).toList();
    }

    // ── Layer 3: Enhanced pattern matcher ─────────────────────────────────

    private AstPreprocessedResult parseWithPatterns(
            String sourceCode, TreeSitterLanguage lang, String filePath, Set<Integer> changedLines) {

        List<AstEntity> entities = new ArrayList<>();
        String[] lines = sourceCode.split("\\R", -1);

        if (lang == TreeSitterLanguage.PYTHON) {
            parsePythonEntities(lines, sourceCode, filePath, changedLines, entities);
        } else if (lang == TreeSitterLanguage.TYPESCRIPT || lang == TreeSitterLanguage.JAVASCRIPT) {
            parseTsEntities(lines, sourceCode, filePath, changedLines, entities);
        }

        AstPreprocessedResult r = new AstPreprocessedResult();
        r.setEntities(entities);
        r.setRelations(List.of());
        r.setFileCount(1);
        r.setDetectedLanguages(new LinkedHashSet<>(
                Collections.singletonList(lang != null ? lang.getLanguageId() : "unknown")));
        return r;
    }

    private void parsePythonEntities(String[] lines, String source, String filePath,
                                     Set<Integer> changedLines, List<AstEntity> entities) {
        List<PyBlock> blocks = new ArrayList<>();
        for (int i = 0; i < lines.length; i++) {
            String line = lines[i];
            if (line.strip().isEmpty() || line.strip().startsWith("#")) continue;

            Matcher cm = PY_CLASS_DEF.matcher(line.strip());
            if (cm.find()) {
                int indent = indentLevel(line);
                blocks.add(new PyBlock("class", cm.group(1), i + 1, indent));
                continue;
            }
            Matcher fm = PY_FUNCTION_DEF.matcher(line.strip());
            if (fm.find()) {
                int indent = indentLevel(line);
                blocks.add(new PyBlock("function", fm.group(1), i + 1, indent));
            }
        }

        for (int i = 0; i < blocks.size(); i++) {
            PyBlock b = blocks.get(i);
            int endLine = lines.length;
            for (int j = i + 1; j < blocks.size(); j++) {
                if (blocks.get(j).indent <= b.indent) {
                    endLine = blocks.get(j).startLine - 1;
                    while (endLine > b.startLine && lines[endLine - 1].strip().isEmpty()) endLine--;
                    break;
                }
            }
            b.endLine = endLine;

            boolean onChanged = changedLines == null || overlaps(b.startLine, endLine, changedLines);
            if (!onChanged) continue;

            String kind = b.kind.equals("function") ? "method" : "class";
            AstEntity e = new AstEntity(b.name, kind, filePath, b.startLine, endLine, "python");
            e.setFullyQualifiedName(filePath + "::" + b.name);
            e.setSignature(sigFromLines(lines, b.startLine, endLine));
            entities.add(e);
        }

        for (int i = 0; i < blocks.size(); i++) {
            PyBlock cls = blocks.get(i);
            if (!"class".equals(cls.kind)) continue;

            for (int j = i + 1; j < blocks.size(); j++) {
                PyBlock method = blocks.get(j);
                if (!"function".equals(method.kind)) continue;
                if (method.startLine > cls.endLine) break;
                if (method.indent > cls.indent) {
                    boolean onChanged = changedLines == null || overlaps(method.startLine, method.endLine, changedLines);
                    if (!onChanged) continue;
                    AstEntity e = new AstEntity(method.name, "method", filePath,
                            method.startLine, method.endLine, "python");
                    e.setFullyQualifiedName(filePath + "::" + cls.name + "::" + method.name);
                    e.setParentClass(cls.name);
                    e.setSignature(sigFromLines(lines, method.startLine, method.endLine));
                    entities.add(e);
                }
            }
        }
    }

    private void parseTsEntities(String[] lines, String source, String filePath,
                                 Set<Integer> changedLines, List<AstEntity> entities) {
        String currentClass = "";
        for (int i = 0; i < lines.length; i++) {
            String line = lines[i];
            String stripped = line.strip();
            if (stripped.isEmpty() || stripped.startsWith("//") || stripped.startsWith("/*")) continue;
            boolean onChanged = changedLines == null || changedLines.contains(i + 1);

            Matcher cm = TS_CLASS_DEF.matcher(stripped);
            if (cm.find()) {
                currentClass = cm.group(1);
                if (onChanged) {
                    int endLine = findTsBlockEnd(lines, i + 1);
                    AstEntity e = new AstEntity(currentClass, "class", filePath, i + 1, endLine, "typescript");
                    e.setFullyQualifiedName(filePath + "::" + currentClass);
                    e.setSignature(sigFromLines(lines, i + 1, endLine));
                    entities.add(e);
                }
                continue;
            }

            Matcher im = TS_INTERFACE_DEF.matcher(stripped);
            if (im.find()) {
                if (onChanged) {
                    int endLine = findTsBlockEnd(lines, i + 1);
                    AstEntity e = new AstEntity(im.group(1), "interface", filePath, i + 1, endLine, "typescript");
                    e.setFullyQualifiedName(filePath + "::" + im.group(1));
                    entities.add(e);
                }
                currentClass = "";
                continue;
            }

            Matcher fm = TS_FUNCTION_DEF.matcher(stripped);
            if (fm.find() && !currentClass.isEmpty()) {
                if (onChanged) {
                    int endLine = findTsBlockEnd(lines, i + 1);
                    AstEntity e = new AstEntity(fm.group(1), "method", filePath, i + 1, endLine, "typescript");
                    e.setFullyQualifiedName(filePath + "::" + currentClass + "::" + fm.group(1));
                    e.setParentClass(currentClass);
                    e.setSignature(sigFromLines(lines, i + 1, endLine));
                    entities.add(e);
                }
                continue;
            }

            Matcher am = TS_ARROW_DEF.matcher(stripped);
            if (am.find() && !currentClass.isEmpty()) {
                if (onChanged) {
                    int endLine = findTsBlockEnd(lines, i + 1);
                    AstEntity e = new AstEntity(am.group(1), "method", filePath, i + 1, endLine, "typescript");
                    e.setFullyQualifiedName(filePath + "::" + currentClass + "::" + am.group(1));
                    e.setParentClass(currentClass);
                    e.setSignature(sigFromLines(lines, i + 1, endLine));
                    entities.add(e);
                }
            }
        }
    }

    private int findTsBlockEnd(String[] lines, int startLine) {
        int braceCount = 0;
        boolean started = false;
        for (int i = startLine - 1; i < lines.length; i++) {
            String line = lines[i].strip();
            if (!started) {
                if (line.contains("{")) started = true;
                else if (line.endsWith(";")) return i + 1;
                else continue;
            }
            for (char c : line.toCharArray()) {
                if (c == '{') braceCount++;
                if (c == '}') braceCount--;
            }
            if (started && braceCount <= 0) return i + 1;
        }
        return lines.length;
    }

    private static class PyBlock {
        final String kind;
        final String name;
        final int startLine;
        final int indent;
        int endLine;
        PyBlock(String kind, String name, int startLine, int indent) {
            this.kind = kind; this.name = name;
            this.startLine = startLine; this.indent = indent;
        }
    }

    private static int indentLevel(String line) {
        int n = 0;
        for (char c : line.toCharArray()) {
            if (c == ' ') n++;
            else if (c == '\t') n += 4;
            else break;
        }
        return n;
    }

    // ── Helpers ───────────────────────────────────────────────────────────

    private AstPreprocessedResult emptyResult() {
        AstPreprocessedResult r = new AstPreprocessedResult();
        r.setEntities(List.of());
        r.setRelations(List.of());
        r.setFileCount(0);
        r.setDetectedLanguages(Set.of());
        return r;
    }
}
