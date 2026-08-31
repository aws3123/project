package com.acme.review.ast;

import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

public class AstPreprocessedResult {
    private List<AstEntity> entities = new ArrayList<>();
    private List<AstRelation> relations = new ArrayList<>();
    private int fileCount;
    private Set<String> detectedLanguages = new LinkedHashSet<>();

    public AstPreprocessedResult() {}

    public AstPreprocessedResult(List<AstEntity> entities, List<AstRelation> relations, int fileCount, Set<String> detectedLanguages) {
        this.entities = entities;
        this.relations = relations;
        this.fileCount = fileCount;
        this.detectedLanguages = detectedLanguages;
    }

    public List<AstEntity> getEntities() { return entities; }
    public void setEntities(List<AstEntity> entities) { this.entities = entities; }

    public List<AstRelation> getRelations() { return relations; }
    public void setRelations(List<AstRelation> relations) { this.relations = relations; }

    public int getFileCount() { return fileCount; }
    public void setFileCount(int fileCount) { this.fileCount = fileCount; }

    public Set<String> getDetectedLanguages() { return detectedLanguages; }
    public void setDetectedLanguages(Set<String> detectedLanguages) { this.detectedLanguages = detectedLanguages; }

    public boolean isEmpty() {
        return entities.isEmpty() && relations.isEmpty();
    }
}