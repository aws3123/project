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
