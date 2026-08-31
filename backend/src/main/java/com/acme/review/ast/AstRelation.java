package com.acme.review.ast;

public class AstRelation {
    private String source;
    private String target;
    private String relationType;

    public AstRelation() {}

    public AstRelation(String source, String target, String relationType) {
        this.source = source;
        this.target = target;
        this.relationType = relationType;
    }

    public String getSource() { return source; }
    public void setSource(String source) { this.source = source; }

    public String getTarget() { return target; }
    public void setTarget(String target) { this.target = target; }

    public String getRelationType() { return relationType; }
    public void setRelationType(String relationType) { this.relationType = relationType; }
}