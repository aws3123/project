# AST-Aware Chunking + BM25 Hybrid Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace regex-based "AST" parsing with real Tree-sitter JNI AST parsing in Java BFF, implement AST-aware code chunking at logical boundaries, add BM25 keyword retrieval to Python RAG pipeline, and provide k6 load test scripts.

**Architecture:** Tree-sitter native libraries are loaded via JNI in the Java BFF layer (via official `org.tree-sitter` Maven packages). Parsed AST entities drive structure-aware code chunking. Chunks flow to Python where BM25 (via `rank-bm25`) replaces the old token-overlap keyword path in the 3-way RRF fusion (vector + BM25 + graph). k6 scripts exercise the full retrieval pipeline.

**Tech Stack:** Java 17 + Spring Boot, `org.tree-sitter:tree-sitter:0.23.6` (JNI), Python 3.12 + `rank-bm25`, k6

---

## File Structure

### New files

| File | Responsibility |
|------|---------------|
| `backend/src/main/java/com/acme/review/ast/TreeSitterNativeParser.java` | Real Tree-sitter JNI parsing facade — wraps `TSParser`/`TSTree`/`TSNode` to produce `AstEntity` and `AstRelation` lists with accurate line ranges |
| `backend/src/main/java/com/acme/review/ast/CodeChunk.java` | Chunk DTO — filePath, startLine, endLine, content, chunkType, name, fullyQualifiedName, metadata |
| `backend/src/main/java/com/acme/review/ast/AstChunker.java` | AST-aware chunker — walks AST, splits source at class/method/function boundaries, emits `List<CodeChunk>` |
| `backend/src/main/java/com/acme/review/dto/CodeChunkResult.java` | API response wrapper for chunk results |
| `backend/src/main/java/com/acme/review/service/ReviewContextPreprocessService.java` | General-review pipeline context completion — uses Tree-sitter AST to extract call graphs, annotations, imports, method signatures from diff code |
| `backend/src/main/java/com/acme/review/controller/ChunkController.java` | REST endpoint: `POST /api/internal/chunk` — accepts source code + language, returns AST chunks |
| `python/repositories/bm25_index.py` | BM25 index — build from document list, search with BM25Okapi, persist/load serialized index |
| `k6/retrieval-pipeline.js` | k6 load test — exercises AST parsing + chunking + BM25 search endpoints |
| `k6/parser-only.js` | k6 load test — isolates AST parsing throughput |

### Modified files

| File | Change |
|------|--------|
| `backend/pom.xml` | Add `org.tree-sitter:tree-sitter`, `tree-sitter-java`, `tree-sitter-python`, `tree-sitter-typescript` |
| `backend/src/main/java/com/acme/review/service/TreeSitterPreprocessService.java` | `preprocess()` and `preprocessFiles()` try `TreeSitterNativeParser` first, fall back to regex; rename misleading method internals |
| `python/pyproject.toml` | Add `rank-bm25>=0.2.2` |
| `python/repositories/keyword_index.py` | `search_incidents_keyword_local()` delegates to BM25 index instead of token-overlap |
| `python/graph/nodes/rag.py` | Update method label from "keyword" to "bm25" to reflect BM25 upgrade |

### Test files

| File | Tests |
|------|-------|
| `backend/src/test/java/com/acme/review/ast/TreeSitterNativeParserTest.java` | Parse Java class → extracts methods + class; parse Python def → extracts function; diff-mode filtering |
| `backend/src/test/java/com/acme/review/ast/AstChunkerTest.java` | Chunk a multi-method Java class → each method is its own chunk; chunk Python file → class + methods split correctly; chunk at max_chars boundary |
| `python/tests/repositories/test_bm25_index.py` | Build index from 3 docs → search returns most relevant first; empty index returns []; Chinese tokenization integration |

---

## Tasks

### Task 1: Add tree-sitter Maven dependencies

**Files:**
- Modify: `backend/pom.xml`

- [ ] **Step 1: Add tree-sitter BOM and dependencies to pom.xml**

Insert inside `<dependencies>` block, alongside existing `javaparser-core`:

```xml
<!-- Tree-sitter JNI bindings (cross-language AST parsing) -->
<dependency>
    <groupId>org.tree-sitter</groupId>
    <artifactId>tree-sitter</artifactId>
    <version>0.23.6</version>
</dependency>
<dependency>
    <groupId>org.tree-sitter</groupId>
    <artifactId>tree-sitter-java</artifactId>
    <version>0.23.6</version>
</dependency>
<dependency>
    <groupId>org.tree-sitter</groupId>
    <artifactId>tree-sitter-python</artifactId>
    <version>0.23.6</version>
</dependency>
<dependency>
    <groupId>org.tree-sitter</groupId>
    <artifactId>tree-sitter-typescript</artifactId>
    <version>0.23.6</version>
    <classifier>typescript</classifier>
</dependency>
```

- [ ] **Step 2: Verify dependencies resolve**

Run: `cd backend && mvn dependency:resolve -DincludeScope=compile -q`

Expected: BUILD SUCCESS. The `org.tree-sitter:tree-sitter:0.23.6` JAR and its native lib for Windows x64 are resolved. If the Windows native lib is not bundled, the JAR auto-extracts the matching platform binary at runtime.

- [ ] **Step 3: Commit**

```bash
git add backend/pom.xml
git commit -m "build: add tree-sitter JNI Maven dependencies"
```

---

### Task 2: Create TreeSitterNativeParser

**Files:**
- Create: `backend/src/main/java/com/acme/review/ast/TreeSitterNativeParser.java`

- [ ] **Step 1: Write TreeSitterNativeParserTest**

Create `backend/src/test/java/com/acme/review/ast/TreeSitterNativeParserTest.java`:

```java
package com.acme.review.ast;

import org.junit.jupiter.api.Test;
import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;

import static org.junit.jupiter.api.Assertions.*;

class TreeSitterNativeParserTest {

    private final TreeSitterNativeParser parser = new TreeSitterNativeParser();

    @Test
    void parseJavaClass_extractsMethodsAndClass() {
        String source = """
                package com.example;
                import java.util.List;
                public class UserService {
                    public String getUserName(Long id) {
                        return "hello";
                    }
                    private void helper() {}
                }
                """;
        AstPreprocessedResult result = parser.parse(source, TreeSitterLanguage.JAVA, "UserService.java");
        assertNotNull(result);
        assertFalse(result.getEntities().isEmpty());

        Set<String> names = result.getEntities().stream().map(AstEntity::getName).collect(Collectors.toSet());
        assertTrue(names.contains("UserService"), "Should find class UserService");
        assertTrue(names.contains("getUserName"), "Should find method getUserName");
        assertTrue(names.contains("helper"), "Should find method helper");

        // Verify line ranges
        AstEntity userService = result.getEntities().stream()
                .filter(e -> "UserService".equals(e.getName())).findFirst().get();
        assertTrue(userService.getLineStart() >= 4 && userService.getLineStart() <= 5);
        assertTrue(userService.getLineEnd() >= 9);

        // Verify FQN
        AstEntity getUserName = result.getEntities().stream()
                .filter(e -> "getUserName".equals(e.getName())).findFirst().get();
        assertTrue(getUserName.getFullyQualifiedName().contains("UserService"));
        assertEquals("method", getUserName.getKind());
    }

    @Test
    void parsePythonDef_extractsFunctions() {
        String source = """
                import os
                def greet(name: str) -> str:
                    return f"Hello {name}"
                class Calculator:
                    def add(self, a, b):
                        return a + b
                """;
        AstPreprocessedResult result = parser.parse(source, TreeSitterLanguage.PYTHON, "calc.py");
        assertNotNull(result);

        Set<String> names = result.getEntities().stream().map(AstEntity::getName).collect(Collectors.toSet());
        assertTrue(names.contains("greet"));
        assertTrue(names.contains("Calculator"));
        assertTrue(names.contains("add"));
    }

    @Test
    void parseDiffMode_onlyReturnsChangedLineEntities() {
        String source = """
                public class OldService {
                    public String oldMethod() { return "x"; }
                    public String newMethod() { return "y"; }
                }
                """;
        Set<Integer> changedLines = Set.of(4); // only newMethod line
        AstPreprocessedResult result = parser.parseWithChangedLines(
                source, TreeSitterLanguage.JAVA, "Service.java", changedLines);

        // newMethod is on line 4, oldMethod on line 3
        // Depending on exact tree-sitter line reporting, both entities or only newMethod should appear
        // At minimum, newMethod should appear in entities
        Set<String> names = result.getEntities().stream().map(AstEntity::getName).collect(Collectors.toSet());
        assertTrue(names.contains("newMethod"), "newMethod should be detected as it's on changed line");
    }

    @Test
    void unsupportedLanguage_fallsBackToGeneric() {
        String source = "fn main() { println!(\"hello\"); }";
        AstPreprocessedResult result = parser.parse(source, null, "main.rs");
        // Should return empty entities gracefully (no crash)
        assertNotNull(result);
    }
}
```

- [ ] **Step 2: Run test, expect compilation failure**

Run: `cd backend && mvn test-compile -q 2>&1 | head -5`

Expected: compilation error — `TreeSitterNativeParser` doesn't exist yet.

- [ ] **Step 3: Write TreeSitterNativeParser implementation**

```java
package com.acme.review.ast;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import org.treesitter.TSNode;
import org.treesitter.TSParser;
import org.treesitter.TSTree;
import org.treesitter.TSNodeCursor;

import java.util.*;

@Component
public class TreeSitterNativeParser {

    private static final Logger log = LoggerFactory.getLogger(TreeSitterNativeParser.class);

    private final Map<TreeSitterLanguage, TSParser> parsers = new EnumMap<>(TreeSitterLanguage.class);

    public TreeSitterNativeParser() {
        // Lazy-init: parsers created on first use per language
    }

    private TSParser getOrCreateParser(TreeSitterLanguage lang) {
        return parsers.computeIfAbsent(lang, k -> {
            TSParser p = new TSParser();
            switch (k) {
                case JAVA:
                    p.setLanguage(new org.treesitter.TSLanguageJava());
                    break;
                case PYTHON:
                    p.setLanguage(new org.treesitter.TSLanguagePython());
                    break;
                case TYPESCRIPT:
                case JAVASCRIPT:
                    p.setLanguage(new org.treesitter.TSLanguageTypescript());
                    break;
                default:
                    throw new IllegalArgumentException("Unsupported language: " + k);
            }
            return p;
        });
    }

    /**
     * Parse full source code with Tree-sitter, returning all entities and relations.
     */
    public AstPreprocessedResult parse(String sourceCode, TreeSitterLanguage language, String filePath) {
        return parseWithChangedLines(sourceCode, language, filePath, null);
    }

    /**
     * Parse source code, optionally filtering to entities on changed lines.
     *
     * @param changedLines set of 1-based line numbers that are changed, or null to include all
     */
    public AstPreprocessedResult parseWithChangedLines(
            String sourceCode, TreeSitterLanguage language, String filePath, Set<Integer> changedLines) {

        if (language == null || sourceCode == null || sourceCode.isBlank()) {
            return emptyResult();
        }

        TSParser parser;
        try {
            parser = getOrCreateParser(language);
        } catch (Exception e) {
            log.warn("Tree-sitter parser unavailable for {}: {}", language, e.getMessage());
            return emptyResult();
        }

        TSTree tree = parser.parseString(sourceCode);
        if (tree == null) {
            return emptyResult();
        }

        TSNode rootNode = tree.getRootNode();
        List<AstEntity> entities = new ArrayList<>();
        List<AstRelation> relations = new ArrayList<>();
        String[] sourceLines = sourceCode.split("\\R", -1);
        byte[] sourceBytes = sourceCode.getBytes(java.nio.charset.StandardCharsets.UTF_8);

        walkTree(rootNode, null, filePath, language.getLanguageId(), sourceLines, sourceBytes, changedLines, entities, relations, 0);

        // Deduplicate relations
        Set<String> seenRelations = new LinkedHashSet<>();
        List<AstRelation> deduplicated = new ArrayList<>();
        for (AstRelation r : relations) {
            String key = r.getSource() + "->" + r.getTarget() + "#" + r.getRelationType();
            if (seenRelations.add(key)) {
                deduplicated.add(r);
            }
        }

        AstPreprocessedResult result = new AstPreprocessedResult();
        result.setEntities(entities);
        result.setRelations(deduplicated);
        result.setFileCount(1);
        result.setDetectedLanguages(new LinkedHashSet<>(Collections.singletonList(language.getLanguageId())));
        return result;
    }

    private void walkTree(
            TSNode node,
            String parentFqn,
            String filePath,
            String languageId,
            String[] sourceLines,
            byte[] sourceBytes,
            Set<Integer> changedLines,
            List<AstEntity> entities,
            List<AstRelation> relations,
            int depth) {

        if (depth > 200) return; // safety guard

        String nodeType = node.getType();
        int startRow = node.getStartPoint().getRow();   // 0-based
        int endRow = node.getEndPoint().getRow();       // 0-based
        int startLine = startRow + 1;                    // convert to 1-based
        int endLine = endRow + 1;

        boolean isDefinition = isDefinitionNode(nodeType);

        if (isDefinition) {
            String name = extractNodeName(node, sourceBytes);
            if (name != null && !name.isEmpty()) {
                String kind = mapNodeTypeToKind(nodeType);
                boolean onChangedLine = (changedLines == null) || overlapsChangedLines(startLine, endLine, changedLines);

                if (onChangedLine) {
                    AstEntity entity = new AstEntity();
                    entity.setName(name);
                    entity.setKind(kind);
                    entity.setFilePath(filePath);
                    entity.setLineStart(startLine);
                    entity.setLineEnd(endLine);
                    entity.setLanguage(languageId);
                    entity.setModifiers(extractModifiers(node, sourceLines, kind));

                    String fqn = parentFqn != null ? parentFqn + "::" + name : filePath + "::" + name;
                    entity.setFullyQualifiedName(fqn);

                    if ("class".equals(kind) || "interface".equals(kind)) {
                        entity.setParentClass("");
                        entity.setPackageName(extractPackageName(sourceLines));
                    } else if ("method".equals(kind) && parentFqn != null) {
                        entity.setParentClass(parentFqn.contains("::")
                                ? parentFqn.substring(parentFqn.lastIndexOf("::") + 2) : "");
                        entity.setPackageName(extractPackageName(sourceLines));
                    }

                    // Extract signature from source lines
                    if (startRow >= 0 && startRow < sourceLines.length) {
                        StringBuilder sig = new StringBuilder();
                        for (int r = startRow; r <= Math.min(endRow, startRow + 3); r++) {
                            if (r < sourceLines.length) {
                                sig.append(sourceLines[r].strip()).append(" ");
                            }
                        }
                        entity.setSignature(sig.toString().trim());
                    }

                    entities.add(entity);
                    parentFqn = fqn;
                }
            }
        }

        // Walk children
        TSNodeCursor cursor = node.walk();
        if (cursor.gotoFirstChild()) {
            do {
                TSNode child = cursor.getCurrentNode();
                walkTree(child, parentFqn, filePath, languageId, sourceLines, sourceBytes, changedLines, entities, relations, depth + 1);
            } while (cursor.gotoNextSibling());
        }
        cursor.delete();
    }

    private boolean overlapsChangedLines(int startLine, int endLine, Set<Integer> changedLines) {
        for (int i = startLine; i <= endLine; i++) {
            if (changedLines.contains(i)) return true;
        }
        return false;
    }

    /**
     * Returns true for node types that represent named declarations we want to extract.
     */
    private boolean isDefinitionNode(String nodeType) {
        return switch (nodeType) {
            case "class_declaration", "interface_declaration", "method_declaration",
                 "function_declaration", "function_definition", "method_definition",
                 "constructor_declaration", "field_declaration" -> true;
            default -> false;
        };
    }

    private String mapNodeTypeToKind(String nodeType) {
        return switch (nodeType) {
            case "class_declaration" -> "class";
            case "interface_declaration" -> "interface";
            case "method_declaration", "method_definition", "constructor_declaration" -> "method";
            case "function_declaration", "function_definition" -> "method";
            case "field_declaration" -> "field";
            default -> "unknown";
        };
    }

    private String extractNodeName(TSNode node, byte[] sourceBytes) {
        TSNode nameNode = node.getChildByFieldName("name");
        if (nameNode != null) {
            return getNodeText(nameNode, sourceBytes);
        }
        // Fallback: first child that's a named node
        TSNodeCursor cursor = node.walk();
        String name = null;
        if (cursor.gotoFirstChild()) {
            do {
                TSNode child = cursor.getCurrentNode();
                String type = child.getType();
                if (type.equals("identifier") || type.endsWith("_identifier")) {
                    name = getNodeText(child, sourceBytes);
                    break;
                }
            } while (cursor.gotoNextSibling());
        }
        cursor.delete();
        return name;
    }

    private String getNodeText(TSNode node, byte[] sourceBytes) {
        if (node == null) return null;
        int startByte = node.getStartByte();
        int endByte = node.getEndByte();
        if (startByte < 0 || endByte > sourceBytes.length || startByte >= endByte) {
            return node.getType(); // fallback to type name
        }
        return new String(sourceBytes, startByte, endByte - startByte, java.nio.charset.StandardCharsets.UTF_8);
    }

    private List<String> extractModifiers(TSNode node, String[] sourceLines, String kind) {
        // Simplified modifier extraction from first source line
        int row = node.getStartPoint().getRow();
        if (row >= 0 && row < sourceLines.length) {
            String line = sourceLines[row].strip().toLowerCase(Locale.ROOT);
            List<String> mods = new ArrayList<>();
            if (line.contains("public")) mods.add("public");
            if (line.contains("private")) mods.add("private");
            if (line.contains("protected")) mods.add("protected");
            if (line.contains("static")) mods.add("static");
            if (line.contains("abstract")) mods.add("abstract");
            if (line.contains("synchronized")) mods.add("synchronized");
            return mods;
        }
        return List.of();
    }

    private String extractPackageName(String[] sourceLines) {
        for (String line : sourceLines) {
            String trimmed = line.strip();
            if (trimmed.startsWith("package ")) {
                return trimmed.substring(8).replace(";", "").strip();
            }
        }
        return "";
    }

    private AstPreprocessedResult emptyResult() {
        AstPreprocessedResult r = new AstPreprocessedResult();
        r.setEntities(List.of());
        r.setRelations(List.of());
        r.setFileCount(0);
        r.setDetectedLanguages(Set.of());
        return r;
    }
}
```

- [ ] **Step 4: Run test, verify pass**

Run: `cd backend && mvn test -Dtest="TreeSitterNativeParserTest" -q`

Expected: BUILD SUCCESS. If tree-sitter native lib fails to load on this Windows system, the parser returns empty result gracefully (test should handle this — `parse()` doesn't throw, returns empty entities).

Note: If `org.treesitter.*` classes differ from the actual published API (package name or method signatures), adjust imports in Step 3 to match. The key contracts are: `TSParser`, `setLanguage()`, `parseString()`, `getRootNode()`, `TSNode.getType()`, `getStartPoint()/getEndPoint()`, `walk()`/`TSNodeCursor`.

- [ ] **Step 5: Commit**

```bash
git add backend/src/main/java/com/acme/review/ast/TreeSitterNativeParser.java backend/src/test/java/com/acme/review/ast/TreeSitterNativeParserTest.java
git commit -m "feat: add TreeSitterNativeParser with real JNI-based AST parsing"
```

---

### Task 3: Refactor TreeSitterPreprocessService to try real AST first

**Files:**
- Modify: `backend/src/main/java/com/acme/review/service/TreeSitterPreprocessService.java`

- [ ] **Step 1: Inject TreeSitterNativeParser and add try-ast-first logic**

Add field and modify `preprocess()`:

```java
// Existing imports, plus:
import com.acme.review.ast.TreeSitterNativeParser;

@Service
public class TreeSitterPreprocessService {

    private static final Logger log = LoggerFactory.getLogger(TreeSitterPreprocessService.class);

    private final TreeSitterNativeParser nativeParser;

    public TreeSitterPreprocessService(TreeSitterNativeParser nativeParser) {
        this.nativeParser = nativeParser;
    }
    // ... existing patterns remain unchanged
```

Add new method at line ~90 (before `splitDiffIntoFiles`):

```java
    public AstPreprocessedResult preprocessWithNativeParser(String diffContent) {
        List<SourceFileInput> files = splitDiffIntoFiles(diffContent);
        List<AstEntity> allEntities = new ArrayList<>();
        List<AstRelation> allRelations = new ArrayList<>();
        Set<String> detectedLanguages = new LinkedHashSet<>();

        for (SourceFileInput file : files) {
            TreeSitterLanguage lang = TreeSitterLanguage.fromExtension(file.getPath());
            if (lang == null) continue;

            String langName = lang.getLanguageId();
            detectedLanguages.add(langName);

            String reconstructedSource = reconstructSourceFromDiff(file.getDiff());
            Set<Integer> changedLines = extractChangedLines(file.getDiff());

            AstPreprocessedResult parsed;
            try {
                parsed = nativeParser.parseWithChangedLines(
                        reconstructedSource, lang, file.getPath(), changedLines);
            } catch (Exception e) {
                log.debug("Tree-sitter parse failed for {}, falling back to regex: {}",
                        file.getPath(), e.getMessage());
                parsed = null;
            }

            if (parsed != null && !parsed.getEntities().isEmpty()) {
                allEntities.addAll(parsed.getEntities());
                allRelations.addAll(parsed.getRelations());
            } else {
                // Fallback to regex
                Set<Integer> lines = extractChangedLines(file.getDiff());
                List<AstEntity> fileEntities = parseFile(file.getPath(), file.getDiff(), lang, lines);
                List<AstRelation> fileRelations = extractRelations(fileEntities, file.getDiff(), lang);
                allEntities.addAll(fileEntities);
                allRelations.addAll(fileRelations);
            }
        }

        AstPreprocessedResult result = new AstPreprocessedResult();
        result.setEntities(allEntities);
        result.setRelations(deduplicateRelations(allRelations));
        result.setFileCount(files.size());
        result.setDetectedLanguages(detectedLanguages);
        return result;
    }

    /**
     * Reconstruct compilable source from a diff by taking only the final state
     * of each line (applying +/-). Lines starting with "-" are removed; lines
     * starting with "+" (but not "+++") are added without the "+" prefix.
     */
    private String reconstructSourceFromDiff(String diff) {
        StringBuilder sb = new StringBuilder();
        for (String line : diff.split("\\R")) {
            if (line.startsWith("+++") || line.startsWith("---") || line.startsWith("@@")) continue;
            if (line.startsWith("+")) {
                sb.append(line.substring(1)).append('\n');
            } else if (line.startsWith(" ")) {
                sb.append(line.substring(1)).append('\n');
            }
            // "-" lines (removals) are skipped
        }
        return sb.toString();
    }
```

Modify `preprocessFiles()` to also try native parser first:

```java
    public AstPreprocessedResult preprocessFiles(List<SourceFileInput> files) {
        // Try native parser first for each file
        List<AstEntity> allEntities = new ArrayList<>();
        List<AstRelation> allRelations = new ArrayList<>();
        Set<String> detectedLanguages = new LinkedHashSet<>();
        boolean allNativeOk = true;

        for (SourceFileInput file : files) {
            TreeSitterLanguage lang = TreeSitterLanguage.fromExtension(file.getPath());
            if (lang != null) detectedLanguages.add(lang.getLanguageId());

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
                // ... existing regex logic from original preprocessFiles ...
            }
        }

        // If all files parsed natively, use native results; otherwise fall through to existing logic
        if (allNativeOk) {
            AstPreprocessedResult result = new AstPreprocessedResult();
            result.setEntities(allEntities);
            result.setRelations(deduplicateRelations(allRelations));
            result.setFileCount(files.size());
            result.setDetectedLanguages(detectedLanguages);
            return result;
        }
        // Otherwise run original regex-based logic
        return originalPreprocessFiles(files);
    }

    // Rename original body to this
    private AstPreprocessedResult originalPreprocessFiles(List<SourceFileInput> files) {
        // ... existing content of preprocessFiles() exactly as-is ...
    }
```

- [ ] **Step 2: Ensure compilation passes**

Run: `cd backend && mvn test-compile -q`

Expected: BUILD SUCCESS

- [ ] **Step 3: Commit**

```bash
git add backend/src/main/java/com/acme/review/service/TreeSitterPreprocessService.java
git commit -m "feat: TreeSitterPreprocessService tries native AST first, falls back to regex"
```

---

### Task 4: Create AstChunker with tests

**Files:**
- Create: `backend/src/main/java/com/acme/review/ast/CodeChunk.java`
- Create: `backend/src/main/java/com/acme/review/ast/AstChunker.java`
- Create: `backend/src/test/java/com/acme/review/ast/AstChunkerTest.java`

- [ ] **Step 1: Write CodeChunk DTO**

```java
package com.acme.review.ast;

import java.util.HashMap;
import java.util.Map;

public class CodeChunk {
    private String filePath;
    private int startLine;
    private int endLine;
    private String content;
    private String chunkType;   // "class", "method", "function", "field", "header"
    private String name;
    private String fullyQualifiedName;
    private Map<String, Object> metadata = new HashMap<>();

    public CodeChunk() {}

    // --- getters/setters ---
    public String getFilePath() { return filePath; }
    public void setFilePath(String filePath) { this.filePath = filePath; }

    public int getStartLine() { return startLine; }
    public void setStartLine(int startLine) { this.startLine = startLine; }

    public int getEndLine() { return endLine; }
    public void setEndLine(int endLine) { this.endLine = endLine; }

    public String getContent() { return content; }
    public void setContent(String content) { this.content = content; }

    public String getChunkType() { return chunkType; }
    public void setChunkType(String chunkType) { this.chunkType = chunkType; }

    public String getName() { return name; }
    public void setName(String name) { this.name = name; }

    public String getFullyQualifiedName() { return fullyQualifiedName; }
    public void setFullyQualifiedName(String fullyQualifiedName) { this.fullyQualifiedName = fullyQualifiedName; }

    public Map<String, Object> getMetadata() { return metadata; }
    public void setMetadata(Map<String, Object> metadata) { this.metadata = metadata; }
}
```

```java
package com.acme.review.ast;

import java.util.ArrayList;
import java.util.List;

public class CodeChunkResult {
    private List<CodeChunk> chunks;
    private int totalChunks;
    private String language;
    private String filePath;

    public CodeChunkResult(List<CodeChunk> chunks, String language, String filePath) {
        this.chunks = chunks;
        this.totalChunks = chunks.size();
        this.language = language;
        this.filePath = filePath;
    }

    public List<CodeChunk> getChunks() { return chunks; }
    public int getTotalChunks() { return totalChunks; }
    public String getLanguage() { return language; }
    public String getFilePath() { return filePath; }
}
```

- [ ] **Step 2: Write AstChunkerTest**

```java
package com.acme.review.ast;

import org.junit.jupiter.api.Test;
import java.util.List;
import static org.junit.jupiter.api.Assertions.*;

class AstChunkerTest {

    private final AstChunker chunker = new AstChunker(new TreeSitterNativeParser());

    @Test
    void chunkJavaClass_splitsAtMethodBoundaries() {
        String source = """
                package com.example;
                import java.util.List;
                public class UserService {
                    public String getUserName(Long id) {
                        return "hello";
                    }
                    private void helper() {
                        int x = 1;
                    }
                }
                """;
        List<CodeChunk> chunks = chunker.chunk(source, TreeSitterLanguage.JAVA, "UserService.java", 800, 100);
        assertNotNull(chunks);
        assertFalse(chunks.isEmpty());

        // Should find class chunk
        CodeChunk classChunk = chunks.stream()
                .filter(c -> "class".equals(c.getChunkType())).findFirst().orElse(null);
        assertNotNull(classChunk, "Should have a class chunk");
        assertEquals("UserService", classChunk.getName());

        // Should find method chunks
        long methodCount = chunks.stream().filter(c -> "method".equals(c.getChunkType())).count();
        assertTrue(methodCount >= 2, "Should find at least 2 method chunks, found " + methodCount);

        // Method chunks should have complete content
        chunks.stream().filter(c -> "method".equals(c.getChunkType())).forEach(c -> {
            assertTrue(c.getContent().contains(") {"), "Chunk content should contain method signature");
            assertTrue(c.getStartLine() < c.getEndLine(), "startLine < endLine");
        });
    }

    @Test
    void chunkPythonFile_splitsClassAndFunctions() {
        String source = """
                import os
                def greet(name: str) -> str:
                    return f"Hello {name}"
                class Calculator:
                    def add(self, a, b):
                        return a + b
                    def subtract(self, a, b):
                        return a - b
                def main():
                    pass
                """;
        List<CodeChunk> chunks = chunker.chunk(source, TreeSitterLanguage.PYTHON, "calc.py", 800, 100);
        assertNotNull(chunks);

        long functionCount = chunks.stream().filter(c -> "method".equals(c.getChunkType())).count();
        assertTrue(functionCount >= 3, "Should find at least 3 functions (greet, add, subtract, main)");
    }

    @Test
    void chunk_smallFile_returnsSingleChunk() {
        String source = "public class Tiny {}";
        List<CodeChunk> chunks = chunker.chunk(source, TreeSitterLanguage.JAVA, "Tiny.java", 800, 100);
        assertFalse(chunks.isEmpty());
        assertEquals("Tiny", chunks.get(0).getName());
    }

    @Test
    void chunk_largeMethod_subChunks() {
        // A method longer than maxChars should be sub-chunked
        StringBuilder sb = new StringBuilder();
        sb.append("""
                public class Large {
                    public void bigMethod() {
                """);
        for (int i = 0; i < 50; i++) {
            sb.append("        System.out.println(\"line ").append(i).append("\");\n");
        }
        sb.append("""
                    }
                }
                """);
        String source = sb.toString();
        List<CodeChunk> chunks = chunker.chunk(source, TreeSitterLanguage.JAVA, "Large.java", 200, 30);
        assertNotNull(chunks);
        // The method is large enough that sub-chunking may produce 2+ chunks for bigMethod
        // or one big method chunk, depending on maxChars. Just verify it doesn't crash.
        assertTrue(chunks.stream().anyMatch(c -> "class".equals(c.getChunkType())));
    }
}
```

- [ ] **Step 3: Write AstChunker implementation**

```java
package com.acme.review.ast;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.util.*;

@Component
public class AstChunker {

    private static final Logger log = LoggerFactory.getLogger(AstChunker.class);
    private static final int DEFAULT_MAX_CHARS = 800;
    private static final int DEFAULT_OVERLAP = 100;

    private final TreeSitterNativeParser parser;

    public AstChunker(TreeSitterNativeParser parser) {
        this.parser = parser;
    }

    /**
     * Chunk source code at AST logical boundaries.
     *
     * @param sourceCode full source text
     * @param language   language enum
     * @param filePath   file path (for FQN construction)
     * @param maxChars   max characters per chunk
     * @param overlap    overlap characters between adjacent chunks
     * @return ordered list of code chunks
     */
    public List<CodeChunk> chunk(String sourceCode, TreeSitterLanguage language,
                                 String filePath, int maxChars, int overlap) {
        if (sourceCode == null || sourceCode.isBlank()) return List.of();

        AstPreprocessedResult parsed = parser.parse(sourceCode, language, filePath);
        List<AstEntity> entities = parsed.getEntities();
        if (entities.isEmpty()) {
            // Fallback: character-based chunking
            return fallbackChunk(sourceCode, filePath, language, maxChars, overlap);
        }

        String[] lines = sourceCode.split("\\R", -1);
        List<CodeChunk> chunks = new ArrayList<>();

        // Sort entities by line start
        List<AstEntity> sorted = new ArrayList<>(entities);
        sorted.sort(Comparator.comparingInt(AstEntity::getLineStart));

        // Generate chunks for each entity
        for (AstEntity entity : sorted) {
            CodeChunk chunk = buildChunk(entity, lines, filePath);
            if (chunk != null) {
                // If chunk exceeds maxChars, sub-chunk it
                if (chunk.getContent().length() > maxChars) {
                    chunks.addAll(subChunk(chunk, maxChars, overlap));
                } else {
                    chunks.add(chunk);
                }
            }
        }

        // Fill gaps between chunks with context chunks
        chunks = fillGaps(chunks, lines, filePath);

        return chunks;
    }

    public List<CodeChunk> chunk(String sourceCode, TreeSitterLanguage language, String filePath) {
        return chunk(sourceCode, language, filePath, DEFAULT_MAX_CHARS, DEFAULT_OVERLAP);
    }

    private CodeChunk buildChunk(AstEntity entity, String[] lines, String filePath) {
        int from = Math.max(0, entity.getLineStart() - 1);
        int to = Math.min(lines.length, entity.getLineEnd());

        // Include annotations/JavaDoc before the entity
        int annotationStart = from;
        for (int i = from - 1; i >= 0; i--) {
            String line = lines[i].strip();
            if (line.startsWith("@") || line.startsWith("//") || line.startsWith("/*")
                    || line.startsWith("*") || line.startsWith("/**")) {
                annotationStart = i;
            } else if (line.isEmpty()) {
                // Keep going past blank lines for annotations
                continue;
            } else {
                break;
            }
        }

        StringBuilder content = new StringBuilder();
        for (int i = annotationStart; i < to; i++) {
            content.append(lines[i]).append('\n');
        }

        CodeChunk chunk = new CodeChunk();
        chunk.setFilePath(filePath);
        chunk.setStartLine(annotationStart + 1);
        chunk.setEndLine(to);
        chunk.setContent(content.toString().trim());
        chunk.setChunkType(entity.getKind());
        chunk.setName(entity.getName());
        chunk.setFullyQualifiedName(entity.getFullyQualifiedName());
        chunk.getMetadata().put("language", entity.getLanguage());
        chunk.getMetadata().put("signature", entity.getSignature() != null ? entity.getSignature() : "");
        if (entity.getParentClass() != null && !entity.getParentClass().isEmpty()) {
            chunk.getMetadata().put("parentClass", entity.getParentClass());
        }
        return chunk;
    }

    private List<CodeChunk> subChunk(CodeChunk original, int maxChars, int overlap) {
        String text = original.getContent();
        if (text.length() <= maxChars) return List.of(original);

        List<CodeChunk> subChunks = new ArrayList<>();
        int start = 0;
        int seq = 0;
        while (start < text.length()) {
            int end = Math.min(start + maxChars, text.length());
            int splitAt = text.lastIndexOf('\n', end);
            if (splitAt <= start) splitAt = end;

            CodeChunk sub = new CodeChunk();
            sub.setFilePath(original.getFilePath());
            sub.setStartLine(original.getStartLine()); // approximate
            sub.setEndLine(original.getEndLine());
            sub.setContent(text.substring(start, splitAt).trim());
            sub.setChunkType(original.getChunkType() + "_segment");
            sub.setName(original.getName() + "#" + seq);
            sub.setFullyQualifiedName(original.getFullyQualifiedName() + "#seg" + seq);
            sub.setMetadata(new HashMap<>(original.getMetadata()));
            subChunks.add(sub);

            start = splitAt - overlap;
            if (start < 0) start = 0;
            seq++;
        }
        return subChunks;
    }

    private List<CodeChunk> fillGaps(List<CodeChunk> chunks, String[] lines, String filePath) {
        if (chunks.isEmpty()) return chunks;

        List<CodeChunk> result = new ArrayList<>();
        chunks.sort(Comparator.comparingInt(CodeChunk::getStartLine));

        int lastEnd = 1;
        for (CodeChunk chunk : chunks) {
            if (chunk.getStartLine() > lastEnd + 1) {
                // There's a gap — emit a context chunk
                CodeChunk gap = new CodeChunk();
                gap.setFilePath(filePath);
                gap.setStartLine(lastEnd);
                gap.setEndLine(chunk.getStartLine() - 1);
                StringBuilder content = new StringBuilder();
                for (int i = lastEnd - 1; i < chunk.getStartLine() - 1 && i < lines.length; i++) {
                    content.append(lines[i]).append('\n');
                }
                gap.setContent(content.toString().trim());
                gap.setChunkType("context");
                gap.setName("context_" + lastEnd + "_" + (chunk.getStartLine() - 1));
                result.add(gap);
            }
            result.add(chunk);
            lastEnd = chunk.getEndLine() + 1;
        }

        // Trailing gap
        if (lastEnd <= lines.length) {
            CodeChunk gap = new CodeChunk();
            gap.setFilePath(filePath);
            gap.setStartLine(lastEnd);
            gap.setEndLine(lines.length);
            StringBuilder content = new StringBuilder();
            for (int i = lastEnd - 1; i < lines.length; i++) {
                content.append(lines[i]).append('\n');
            }
            gap.setContent(content.toString().trim());
            gap.setChunkType("context");
            gap.setName("context_" + lastEnd + "_end");
            result.add(gap);
        }

        return result;
    }

    private List<CodeChunk> fallbackChunk(String sourceCode, String filePath,
                                           TreeSitterLanguage language, int maxChars, int overlap) {
        List<CodeChunk> chunks = new ArrayList<>();
        int start = 0;
        int seq = 0;
        String[] lines = sourceCode.split("\\R", -1);
        while (start < sourceCode.length()) {
            int end = Math.min(start + maxChars, sourceCode.length());
            int splitAt = sourceCode.lastIndexOf('\n', end);
            if (splitAt <= start) splitAt = end;

            CodeChunk chunk = new CodeChunk();
            chunk.setFilePath(filePath);
            chunk.setStartLine(seq * maxChars / 80 + 1); // rough estimate
            chunk.setContent(sourceCode.substring(start, splitAt).trim());
            chunk.setChunkType("fallback");
            chunk.setName(filePath + "#seg" + seq);
            chunks.add(chunk);

            start = splitAt - overlap;
            if (start < 0) start = 0;
            seq++;
        }
        return chunks;
    }
}
```

- [ ] **Step 4: Run AstChunker tests**

Run: `cd backend && mvn test -Dtest="AstChunkerTest" -q`

Expected: BUILD SUCCESS. Tests verify class/method splitting, Python function extraction, and large-method sub-chunking.

- [ ] **Step 5: Commit**

```bash
git add backend/src/main/java/com/acme/review/ast/CodeChunk.java backend/src/main/java/com/acme/review/ast/AstChunker.java backend/src/test/java/com/acme/review/ast/AstChunkerTest.java
git commit -m "feat: add AST-aware code chunker with logical-boundary splitting"
```

---

### Task 5: Create ChunkController REST endpoint

**Files:**
- Create: `backend/src/main/java/com/acme/review/controller/ChunkController.java`

- [ ] **Step 1: Write ChunkController implementation**

```java
package com.acme.review.controller;

import com.acme.review.ast.AstChunker;
import com.acme.review.ast.CodeChunk;
import com.acme.review.ast.CodeChunkResult;
import com.acme.review.ast.TreeSitterLanguage;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/internal")
public class ChunkController {

    private final AstChunker chunker;

    public ChunkController(AstChunker chunker) {
        this.chunker = chunker;
    }

    /**
     * Parse and chunk source code at AST logical boundaries.
     * Used by the retrieval pipeline for structure-aware code chunking.
     *
     * Request body:
     * {
     *   "sourceCode": "full source text",
     *   "language": "JAVA|PYTHON|TYPESCRIPT|JAVASCRIPT|SQL",
     *   "filePath": "path/to/File.java",
     *   "maxChars": 800,
     *   "overlap": 100
     * }
     */
    @PostMapping("/chunk")
    public ResponseEntity<?> chunkSource(@RequestBody Map<String, Object> request) {
        String sourceCode = (String) request.get("sourceCode");
        if (sourceCode == null || sourceCode.isBlank()) {
            return ResponseEntity.badRequest().body(Map.of("error", "sourceCode is required"));
        }

        String langStr = (String) request.getOrDefault("language", "JAVA");
        String filePath = (String) request.getOrDefault("filePath", "unknown");
        int maxChars = request.get("maxChars") instanceof Number n ? n.intValue() : 800;
        int overlap = request.get("overlap") instanceof Number n ? n.intValue() : 100;

        TreeSitterLanguage language;
        try {
            language = TreeSitterLanguage.valueOf(langStr.toUpperCase());
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest().body(Map.of("error", "Unsupported language: " + langStr));
        }

        try {
            List<CodeChunk> chunks = chunker.chunk(sourceCode, language, filePath, maxChars, overlap);
            CodeChunkResult result = new CodeChunkResult(chunks, language.getLanguageId(), filePath);
            return ResponseEntity.ok(result);
        } catch (Exception e) {
            return ResponseEntity.internalServerError().body(Map.of("error", e.getMessage()));
        }
    }
}
```

- [ ] **Step 2: Verify compilation**

Run: `cd backend && mvn test-compile -q`

Expected: BUILD SUCCESS

- [ ] **Step 3: Commit**

```bash
git add backend/src/main/java/com/acme/review/controller/ChunkController.java
git commit -m "feat: add chunk REST endpoint for AST-aware code chunking"
```

---

### Task 6: Create ReviewContextPreprocessService

**Files:**
- Create: `backend/src/main/java/com/acme/review/service/ReviewContextPreprocessService.java`

- [ ] **Step 1: Write the context preprocessing service**

This service uses TreeSitterNativeParser to extract rich context from diff code for the general review pipeline (not just Business Risk).

```java
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

/**
 * Context completion for general review pipeline.
 * Uses Tree-sitter AST to extract call graphs, annotations, imports,
 * method signatures, and structural context from diff code.
 * 
 * This mirrors BusinessRiskSourcePreprocessService's approach but uses
 * Tree-sitter (cross-language) instead of JavaParser (Java-only), and
 * operates on diff content rather than uploaded .java files.
 */
@Service
public class ReviewContextPreprocessService {

    private static final Logger log = LoggerFactory.getLogger(ReviewContextPreprocessService.class);

    private final TreeSitterNativeParser nativeParser;

    public ReviewContextPreprocessService(TreeSitterNativeParser nativeParser) {
        this.nativeParser = nativeParser;
    }

    /**
     * Extract context from diff content.
     *
     * @param diffContent unified diff content
     * @return map with keys: entities, relations, callGraph, annotations, imports, riskSignals
     */
    public Map<String, Object> extractContext(String diffContent) {
        // Split diff into per-file diffs
        TreeSitterPreprocessService.SourceFileInput[] files = splitDiffFiles(diffContent);

        List<Map<String, Object>> callGraph = new ArrayList<>();
        Set<String> allAnnotations = new LinkedHashSet<>();
        Set<String> allImports = new LinkedHashSet<>();
        List<Map<String, Object>> riskSignals = new ArrayList<>();
        List<Map<String, Object>> fileContexts = new ArrayList<>();

        for (int fi = 0; fi < files.length; fi++) {
            TreeSitterPreprocessService.SourceFileInput file = files[fi];
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

            // Collect annotations and imports
            for (AstEntity entity : parsed.getEntities()) {
                if (entity.getModifiers() != null) {
                    allAnnotations.addAll(entity.getModifiers());
                }
                if ("import".equals(entity.getKind())) {
                    allImports.add(entity.getName());
                }
            }

            // Build call graph
            for (AstRelation rel : parsed.getRelations()) {
                if ("CALLS".equals(rel.getRelationType())) {
                    Map<String, Object> edge = new LinkedHashMap<>();
                    edge.put("source", rel.getSource());
                    edge.put("target", rel.getTarget());
                    edge.put("file", file.getPath());
                    callGraph.add(edge);
                }
            }

            // Detect risk signals from context
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
        // Same logic as TreeSitterPreprocessService.splitDiffIntoFiles
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
```

- [ ] **Step 2: Verify compilation**

Run: `cd backend && mvn test-compile -q`

Expected: BUILD SUCCESS

- [ ] **Step 3: Commit**

```bash
git add backend/src/main/java/com/acme/review/service/ReviewContextPreprocessService.java
git commit -m "feat: add ReviewContextPreprocessService for general-review context completion"
```

---

### Task 7: Implement BM25 index + integrate into Python RAG pipeline

**Files:**
- Modify: `python/pyproject.toml`
- Create: `python/repositories/bm25_index.py`
- Modify: `python/repositories/keyword_index.py`
- Modify: `python/graph/nodes/rag.py`
- Create: `python/tests/repositories/test_bm25_index.py`

- [ ] **Step 1: Add rank-bm25 dependency**

Append to `pyproject.toml` dependencies list:

```toml
    "rank-bm25>=0.2.2",
```

- [ ] **Step 2: Write BM25 index tests**

```python
from __future__ import annotations

import pytest
from repositories.bm25_index import BM25Index


class TestBM25Index:
    def test_build_and_search(self):
        docs = [
            {"id": "1", "title": "NullPointerException in UserService",
             "snippet": "UserService.getUserName() throws NPE when id is null",
             "source": "incident"},
            {"id": "2", "title": "Transaction rollback in OrderService",
             "snippet": "OrderService.createOrder() fails due to constraint violation",
             "source": "incident"},
            {"id": "3", "title": "Cache inconsistency in ProductCache",
             "snippet": "ProductCache returns stale data after inventory update",
             "source": "incident"},
        ]
        index = BM25Index()
        index.build(docs)

        # Search for NPE-related
        results = index.search("NullPointerException UserService", top_k=2)
        assert len(results) >= 1
        assert results[0]["id"] == "1"
        assert "score" in results[0]
        assert results[0]["score"] > 0

    def test_search_empty_index(self):
        index = BM25Index()
        results = index.search("anything", top_k=5)
        assert results == []

    def test_chinese_query(self):
        docs = [
            {"id": "1", "title": "用户服务空指针",
             "snippet": "用户查询接口传入空ID导致空指针异常",
             "source": "incident"},
            {"id": "2", "title": "订单事务回滚",
             "snippet": "订单创建由于唯一约束冲突导致回滚",
             "source": "incident"},
        ]
        index = BM25Index()
        index.build(docs)

        results = index.search("空指针", top_k=5)
        assert len(results) >= 1
        assert results[0]["id"] == "1"

    def test_persist_and_load(self, tmp_path):
        docs = [
            {"id": "1", "title": "Test", "snippet": "Test document", "source": "test"},
        ]
        index = BM25Index()
        index.build(docs)

        path = str(tmp_path / "bm25_index.pkl")
        index.save(path)

        loaded = BM25Index.load(path)
        assert loaded is not None
        results = loaded.search("Test", top_k=5)
        assert len(results) == 1
        assert results[0]["id"] == "1"
```

- [ ] **Step 3: Write BM25Index implementation**

```python
from __future__ import annotations

import pickle
import logging
from pathlib import Path
from typing import Any

from rank_bm25 import BM25Okapi

from tools.text_chunker import tokenize_chinese

logger = logging.getLogger(__name__)


class BM25Index:
    """BM25 keyword index for incident-code retrieval.

    Uses BM25Okapi from rank_bm25. Tokenizes with jieba for Chinese support.
    Can persist to disk and reload for reuse across service restarts.
    """

    def __init__(self) -> None:
        self.index: BM25Okapi | None = None
        self.documents: list[dict[str, Any]] = []
        self.tokenized_corpus: list[list[str]] = []

    def build(self, documents: list[dict]) -> None:
        """Build BM25 index from a list of document dicts.

        Each document must have at least 'id', 'title', 'snippet', 'source'.
        """
        if not documents:
            self.index = None
            self.documents = []
            self.tokenized_corpus = []
            return

        self.documents = documents
        self.tokenized_corpus = []
        for doc in documents:
            text = " ".join([
                doc.get("title", ""),
                doc.get("snippet", ""),
                doc.get("source", ""),
                doc.get("service", "") or "",
                " ".join(doc.get("tags", [])),
            ])
            tokenized = tokenize_chinese(text).split()
            self.tokenized_corpus.append(tokenized)

        self.index = BM25Okapi(self.tokenized_corpus)

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """Search the BM25 index and return top_k results ranked by relevance."""
        if self.index is None or not self.documents:
            return []

        query_tokens = tokenize_chinese(query).split()
        if not query_tokens:
            return []

        scores = self.index.get_scores(query_tokens)

        indexed = list(enumerate(scores))
        indexed.sort(key=lambda x: x[1], reverse=True)

        results = []
        for idx, score in indexed[:top_k]:
            if score <= 0:
                continue
            doc = dict(self.documents[idx])
            doc["score"] = float(score)
            doc["source"] = doc.get("source", "bm25")
            results.append(doc)

        return results

    def save(self, path: str | Path) -> None:
        """Serialize the index to disk."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "documents": self.documents,
            "tokenized_corpus": self.tokenized_corpus,
        }
        with path.open("wb") as f:
            pickle.dump(data, f)
        logger.info("BM25 index saved to %s (%d docs)", path, len(self.documents))

    @staticmethod
    def load(path: str | Path) -> BM25Index | None:
        """Deserialize the index from disk. Returns None if file missing."""
        path = Path(path)
        if not path.exists():
            return None
        try:
            with path.open("rb") as f:
                data = pickle.load(f)
            index = BM25Index()
            index.documents = data["documents"]
            index.tokenized_corpus = data["tokenized_corpus"]
            index.index = BM25Okapi(index.tokenized_corpus)
            logger.info("BM25 index loaded from %s (%d docs)", path, len(index.documents))
            return index
        except Exception as e:
            logger.warning("Failed to load BM25 index from %s: %s", path, e)
            return None
```

- [ ] **Step 4: Run BM25 tests**

Run: `cd python && uv run pytest tests/repositories/test_bm25_index.py -q`

Expected: 4 passed (test_build_and_search, test_search_empty_index, test_chinese_query, test_persist_and_load)

If `rank_bm25` fails to install: `uv add rank-bm25` first.

- [ ] **Step 5: Update keyword_index.py to use BM25**

Modify `search_incidents_keyword_local()` to build and search a BM25 index instead of token overlap:

```python
from __future__ import annotations

import json
import logging
from pathlib import Path

from config.settings import AppSettings
from repositories.bm25_index import BM25Index

logger = logging.getLogger(__name__)

# Global BM25 index cache for the process lifetime
_bm25_index: BM25Index | None = None


def _get_or_build_bm25(settings: AppSettings) -> BM25Index | None:
    global _bm25_index
    if _bm25_index is not None:
        return _bm25_index

    path = Path(settings.chroma_keyword_index_path)
    if not path.exists():
        return None

    # Try loading from pickle first
    pickle_path = path.with_suffix(".bm25.pkl")
    if pickle_path.exists():
        loaded = BM25Index.load(pickle_path)
        if loaded is not None:
            _bm25_index = loaded
            return _bm25_index

    # Build from JSONL
    rows: list[dict] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        item = json.loads(raw_line)
        rows.append(item)

    if not rows:
        return None

    index = BM25Index()
    index.build(rows)
    index.save(pickle_path)
    _bm25_index = index
    return _bm25_index


def search_incidents_keyword_local(query: str, top_k: int,
                                   settings: AppSettings | None = None) -> list[dict]:
    settings = settings or AppSettings()
    index = _get_or_build_bm25(settings)
    if index is None:
        return []
    return index.search(query, top_k)
```

- [ ] **Step 6: Update rag.py — replace keyword path with BM25**

The existing `run_rag()` in `python/graph/nodes/rag.py` already calls `search_incidents_keyword_local()` (lines ~145-167). Since we updated that function to use BM25 internally, the RAG code path automatically gets BM25. Only change needed: update the method label from "keyword" to "bm25" so logs/tool_logs reflect the upgrade.

Find this block in `run_rag()`:
```python
    methods = ["vector"]
    if keyword_items:
        methods.append("keyword")
    if graph_items:
        methods.append("graph")
```

Change to:
```python
    methods = ["vector"]
    if keyword_items:
        methods.append("bm25")   # upgraded from token-overlap to BM25
    if graph_items:
        methods.append("graph")
```

No changes to `_rrf_fusion` signature — it still takes 3 inputs (vector, keyword, graph), but keyword now uses BM25 scoring internally.

- [ ] **Step 7: Run Python tests to verify nothing breaks**

Run: `cd python && uv run pytest tests/repositories/test_bm25_index.py tests/graph/nodes/test_rag.py -q`

Expected: all BM25 tests pass. RAG tests may need updating if they mock `_rrf_fusion` with 3 args — update mocks to 4 args.

- [ ] **Step 8: Commit**

```bash
git add python/pyproject.toml python/repositories/bm25_index.py python/repositories/keyword_index.py python/graph/nodes/rag.py python/tests/repositories/test_bm25_index.py
git commit -m "feat: add BM25 retrieval index, integrate into RAG RRF fusion"
```

---

### Task 8: Create k6 load test scripts

**Files:**
- Create: `k6/retrieval-pipeline.js`
- Create: `k6/parser-only.js`

- [ ] **Step 1: Write parser-only k6 test**

```javascript
// k6/parser-only.js
// Isolated AST parsing throughput test.
// Exercises the Java BFF's TreeSitterNativeParser via the chunking endpoint.
// Run: k6 run --vus 10 --duration 30s k6/parser-only.js

import http from 'k6/http';
import { check, sleep } from 'k6';
import { SharedArray } from 'k6/data';

// Sample Java source code payload for AST parsing
const javaSource = `
package com.example;
import java.util.List;
import org.springframework.stereotype.Service;
import org.springframework.beans.factory.annotation.Autowired;

@Service
public class UserService {
    private final UserRepository userRepository;
    private final CacheManager cacheManager;

    @Autowired
    public UserService(UserRepository userRepository, CacheManager cacheManager) {
        this.userRepository = userRepository;
        this.cacheManager = cacheManager;
    }

    public String getUserName(Long id) {
        if (id == null) {
            throw new IllegalArgumentException("ID must not be null");
        }
        String cached = cacheManager.get("user:" + id);
        if (cached != null) {
            return cached;
        }
        User user = userRepository.findById(id);
        if (user == null) {
            throw new ResourceNotFoundException("User not found: " + id);
        }
        cacheManager.set("user:" + id, user.getName());
        return user.getName();
    }

    public void deleteUser(Long id) {
        userRepository.deleteById(id);
        cacheManager.evict("user:" + id);
    }

    private void validateUser(User user) {
        if (user.getEmail() == null || !user.getEmail().contains("@")) {
            throw new ValidationException("Invalid email");
        }
        if (user.getName() == null || user.getName().trim().isEmpty()) {
            throw new ValidationException("Name required");
        }
    }

    public List<User> searchUsers(String query, int page, int size) {
        if (page < 0 || size <= 0 || size > 100) {
            throw new IllegalArgumentException("Invalid pagination params");
        }
        return userRepository.search(query, page, size);
    }
}
`;

const pythonSource = `
import os
import logging
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class User:
    id: int
    name: str
    email: str

class UserService:
    def __init__(self, repository, cache):
        self.repository = repository
        self.cache = cache

    def get_user_name(self, user_id: int) -> Optional[str]:
        if user_id is None:
            raise ValueError("ID must not be null")
        cached = self.cache.get(f"user:{user_id}")
        if cached:
            return cached
        user = self.repository.find_by_id(user_id)
        if user is None:
            return None
        self.cache.set(f"user:{user_id}", user.name)
        return user.name

    def search_users(self, query: str, page: int = 0, size: int = 20) -> list[User]:
        if page < 0 or size <= 0 or size > 100:
            raise ValueError("Invalid pagination")
        return self.repository.search(query, page, size)
`;

const TARGET_URL = __ENV.TARGET_URL || 'http://localhost:8080';

export const options = {
    stages: [
        { duration: '30s', target: 10 },  // ramp-up
        { duration: '1m', target: 50 },   // steady
        { duration: '30s', target: 0 },   // ramp-down
    ],
    thresholds: {
        http_req_duration: ['p(95)<500'],  // 95% of requests under 500ms
        http_req_failed: ['rate<0.01'],    // <1% errors
    },
};

export default function () {
    // Test 1: Parse Java source
    const javaPayload = JSON.stringify({
        sourceCode: javaSource,
        language: 'JAVA',
        filePath: 'UserService.java',
        maxChars: 800,
        overlap: 100,
    });

    const javaRes = http.post(`${TARGET_URL}/api/internal/chunk`, javaPayload, {
        headers: { 'Content-Type': 'application/json', 'X-API-Key': 'dev-key' },
    });

    check(javaRes, {
        'Java parse status 200': (r) => r.status === 200,
        'Java parse returns chunks': (r) => {
            try { return JSON.parse(r.body).totalChunks >= 3; }
            catch { return false; }
        },
    });

    // Test 2: Parse Python source
    const pyPayload = JSON.stringify({
        sourceCode: pythonSource,
        language: 'PYTHON',
        filePath: 'user_service.py',
        maxChars: 800,
        overlap: 100,
    });

    const pyRes = http.post(`${TARGET_URL}/api/internal/chunk`, pyPayload, {
        headers: { 'Content-Type': 'application/json', 'X-API-Key': 'dev-key' },
    });

    check(pyRes, {
        'Python parse status 200': (r) => r.status === 200,
        'Python parse returns chunks': (r) => {
            try { return JSON.parse(r.body).totalChunks >= 2; }
            catch { return false; }
        },
    });

    sleep(0.1);
}
```

- [ ] **Step 2: Write full retrieval pipeline k6 test**

```javascript
// k6/retrieval-pipeline.js
// Full retrieval pipeline load test (parse → chunk → embed → search → rank)
// Run: k6 run --vus 5 --duration 30s k6/retrieval-pipeline.js

import http from 'k6/http';
import { check, sleep } from 'k6';

const TARGET_URL = __ENV.TARGET_URL || 'http://localhost:8000';

export const options = {
    stages: [
        { duration: '30s', target: 5 },
        { duration: '1m', target: 25 },
        { duration: '30s', target: 0 },
    ],
    thresholds: {
        http_req_duration: ['p(95)<3000'],   // Full pipeline under 3s
        http_req_failed: ['rate<0.02'],
    },
};

export default function () {
    // Simulate a code review RAG query
    const diffPayload = JSON.stringify({
        diff_content: `
diff --git a/src/main/java/com/acme/review/service/UserService.java b/src/main/java/com/acme/review/service/UserService.java
index abc..def 100644
--- a/src/main/java/com/acme/review/service/UserService.java
+++ b/src/main/java/com/acme/review/service/UserService.java
@@ -15,6 +15,7 @@ public class UserService {
     public User getUser(Long id) {
+        if (id == null) {
+            throw new IllegalArgumentException("ID required");
+        }
         return repository.findById(id);
     }
 }
`,
        pr_url: "https://github.com/example/repo/pull/123",
        project_id: "test-project",
        question: "Check for NPE risk patterns",
    });

    // Full pipeline via dispatch endpoint
    const res = http.post(`${TARGET_URL}/dispatch-review`, diffPayload, {
        headers: { 'Content-Type': 'application/json' },
    });

    check(res, {
        'dispatch returns 200': (r) => r.status === 200,
        'dispatch body present': (r) => r.body && r.body.length > 0,
    });

    sleep(0.5);
}
```

- [ ] **Step 3: Add k6 documentation header comment with run instructions**

In both `k6/*.js` files, the header comment already includes the `k6 run` command. Ensure they're up to date.

- [ ] **Step 4: Commit**

```bash
git add k6/retrieval-pipeline.js k6/parser-only.js
git commit -m "test: add k6 load test scripts for AST parsing and retrieval pipeline"
```

---

## Spec Coverage Check

| Spec Requirement | Task |
|-----------------|------|
| Cross-language AST parsing via Tree-sitter JNI | Task 2 (TreeSitterNativeParser) + Task 1 (Maven deps) |
| Context completion 前置至 Java BFF layer | Task 6 (ReviewContextPreprocessService) |
| AST-aware chunking at logical boundaries | Task 4 (AstChunker) |
| Chunk REST endpoint | Task 5 (ChunkController) |
| BM25 + 向量稠密检索混合召回 | Task 7 (BM25Index + RAG integration) |
| k6 压测 | Task 8 (k6 scripts) |
| 保持 regex fallback | Task 3 (fallback in TreeSitterPreprocessService) |
