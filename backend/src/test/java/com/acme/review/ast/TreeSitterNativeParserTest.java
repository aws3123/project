package com.acme.review.ast;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.util.Set;
import java.util.stream.Collectors;

import static org.junit.jupiter.api.Assertions.*;

class TreeSitterNativeParserTest {

    private TreeSitterNativeParser parser;

    @BeforeEach
    void setUp() {
        parser = new TreeSitterNativeParser();
    }

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
    void parseWithChangedLines_filtersByChangedLines() {
        String source = """
                public class Service {
                    public String oldMethod() { return "x"; }
                    public String newMethod() { return "y"; }
                }
                """;
        Set<Integer> changedLines = Set.of(3);
        AstPreprocessedResult result = parser.parseWithChangedLines(
                source, TreeSitterLanguage.JAVA, "Service.java", changedLines);

        Set<String> names = result.getEntities().stream().map(AstEntity::getName).collect(Collectors.toSet());
        assertTrue(names.contains("newMethod"), "newMethod should be on changed line");
    }

    @Test
    void unsupportedLanguage_returnsEmpty() {
        String source = "fn main() { println!(\"hello\"); }";
        AstPreprocessedResult result = parser.parse(source, null, "main.rs");
        assertNotNull(result);
        assertTrue(result.getEntities().isEmpty());
    }

    @Test
    void emptySource_returnsEmpty() {
        AstPreprocessedResult result = parser.parse("", TreeSitterLanguage.JAVA, "empty.java");
        assertNotNull(result);
        assertTrue(result.getEntities().isEmpty());
    }
}
