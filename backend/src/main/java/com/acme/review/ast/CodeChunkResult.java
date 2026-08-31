package com.acme.review.ast;

import java.util.List;

public class CodeChunkResult {
    private List<CodeChunk> chunks;
    private int totalChunks;
    private String language;
    private String filePath;

    public CodeChunkResult() {}

    public CodeChunkResult(List<CodeChunk> chunks, String language, String filePath) {
        this.chunks = chunks;
        this.totalChunks = chunks.size();
        this.language = language;
        this.filePath = filePath;
    }

    public List<CodeChunk> getChunks() { return chunks; }
    public void setChunks(List<CodeChunk> chunks) { this.chunks = chunks; this.totalChunks = chunks.size(); }
    public int getTotalChunks() { return totalChunks; }
    public String getLanguage() { return language; }
    public void setLanguage(String language) { this.language = language; }
    public String getFilePath() { return filePath; }
    public void setFilePath(String filePath) { this.filePath = filePath; }
}
