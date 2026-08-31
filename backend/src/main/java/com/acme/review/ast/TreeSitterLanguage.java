package com.acme.review.ast;

import java.util.Locale;

public enum TreeSitterLanguage {
    JAVA("java", ".java"),
    PYTHON("python", ".py"),
    TYPESCRIPT("typescript", ".ts", ".tsx"),
    JAVASCRIPT("javascript", ".js", ".jsx"),
    SQL("sql", ".sql");

    private final String languageId;
    private final String[] extensions;

    TreeSitterLanguage(String languageId, String... extensions) {
        this.languageId = languageId;
        this.extensions = extensions;
    }

    public String getLanguageId() {
        return languageId;
    }

    public String[] getExtensions() {
        return extensions;
    }

    public static TreeSitterLanguage fromExtension(String path) {
        String lower = path.toLowerCase(Locale.ROOT);
        for (TreeSitterLanguage lang : values()) {
            for (String ext : lang.extensions) {
                if (lower.endsWith(ext)) {
                    return lang;
                }
            }
        }
        return null;
    }
}