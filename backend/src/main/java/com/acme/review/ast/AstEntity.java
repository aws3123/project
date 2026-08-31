package com.acme.review.ast;

import java.util.ArrayList;
import java.util.List;

public class AstEntity {
    private String name;
    private String kind;
    private String filePath;
    private int lineStart;
    private int lineEnd;
    private String language;
    private List<String> modifiers = new ArrayList<>();
    private String signature;
    private String fullyQualifiedName;
    private String parentClass;
    private String packageName;

    public AstEntity() {}

    public AstEntity(String name, String kind, String filePath, int lineStart, int lineEnd, String language) {
        this.name = name;
        this.kind = kind;
        this.filePath = filePath;
        this.lineStart = lineStart;
        this.lineEnd = lineEnd;
        this.language = language;
    }

    public String getName() { return name; }
    public void setName(String name) { this.name = name; }

    public String getKind() { return kind; }
    public void setKind(String kind) { this.kind = kind; }

    public String getFilePath() { return filePath; }
    public void setFilePath(String filePath) { this.filePath = filePath; }

    public int getLineStart() { return lineStart; }
    public void setLineStart(int lineStart) { this.lineStart = lineStart; }

    public int getLineEnd() { return lineEnd; }
    public void setLineEnd(int lineEnd) { this.lineEnd = lineEnd; }

    public String getLanguage() { return language; }
    public void setLanguage(String language) { this.language = language; }

    public List<String> getModifiers() { return modifiers; }
    public void setModifiers(List<String> modifiers) { this.modifiers = modifiers; }

    public String getSignature() { return signature; }
    public void setSignature(String signature) { this.signature = signature; }

    public String getFullyQualifiedName() { return fullyQualifiedName; }
    public void setFullyQualifiedName(String fullyQualifiedName) { this.fullyQualifiedName = fullyQualifiedName; }

    public String getParentClass() { return parentClass; }
    public void setParentClass(String parentClass) { this.parentClass = parentClass; }

    public String getPackageName() { return packageName; }
    public void setPackageName(String packageName) { this.packageName = packageName; }
}