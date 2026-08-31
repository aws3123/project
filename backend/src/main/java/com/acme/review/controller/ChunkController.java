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
