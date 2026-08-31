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

    public List<CodeChunk> chunk(String sourceCode, TreeSitterLanguage language,
                                 String filePath, int maxChars, int overlap) {
        if (sourceCode == null || sourceCode.isBlank()) return List.of();

        AstPreprocessedResult parsed = parser.parse(sourceCode, language, filePath);
        List<AstEntity> entities = parsed.getEntities();
        if (entities.isEmpty()) {
            return fallbackChunk(sourceCode, filePath, language, maxChars, overlap);
        }

        String[] lines = sourceCode.split("\\R", -1);
        List<CodeChunk> chunks = new ArrayList<>();

        List<AstEntity> sorted = new ArrayList<>(entities);
        sorted.sort(Comparator.comparingInt(AstEntity::getLineStart));

        for (AstEntity entity : sorted) {
            CodeChunk chunk = buildChunk(entity, lines, filePath);
            if (chunk != null) {
                if (chunk.getContent().length() > maxChars) {
                    chunks.addAll(subChunk(chunk, maxChars, overlap));
                } else {
                    chunks.add(chunk);
                }
            }
        }

        chunks = fillGaps(chunks, lines, filePath);
        return chunks;
    }

    public List<CodeChunk> chunk(String sourceCode, TreeSitterLanguage language, String filePath) {
        return chunk(sourceCode, language, filePath, DEFAULT_MAX_CHARS, DEFAULT_OVERLAP);
    }

    private CodeChunk buildChunk(AstEntity entity, String[] lines, String filePath) {
        int from = Math.max(0, entity.getLineStart() - 1);
        int to = Math.min(lines.length, entity.getLineEnd());

        int annotationStart = from;
        for (int i = from - 1; i >= 0; i--) {
            String line = lines[i].strip();
            if (line.startsWith("@") || line.startsWith("//") || line.startsWith("/*")
                    || line.startsWith("*") || line.startsWith("/**")) {
                annotationStart = i;
            } else if (line.isEmpty()) {
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
            sub.setStartLine(original.getStartLine());
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
        while (start < sourceCode.length()) {
            int end = Math.min(start + maxChars, sourceCode.length());
            int splitAt = sourceCode.lastIndexOf('\n', end);
            if (splitAt <= start) splitAt = end;

            CodeChunk chunk = new CodeChunk();
            chunk.setFilePath(filePath);
            chunk.setStartLine(seq * maxChars / 80 + 1);
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
