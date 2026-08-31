package com.acme.review.service;

import com.acme.review.dto.BusinessRiskAnalysisHints;
import com.acme.review.dto.BusinessRiskBudgetDecision;
import com.acme.review.dto.BusinessRiskLineMap;
import com.acme.review.dto.BusinessRiskPreparedMethod;
import com.acme.review.dto.BusinessRiskPreparedSourceFile;
import com.acme.review.dto.BusinessRiskSourcePackage;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class BusinessRiskPayloadBudgetServiceTest {

    @Test
    void applyBudgetShouldTrimLargePayloadWithoutThrowing() throws Exception {
        BusinessRiskPayloadBudgetService service = new BusinessRiskPayloadBudgetService(new ObjectMapper());
        setField(service, "maxPreparedBytes", 300L);
        setField(service, "trimToBytes", 200L);

        BusinessRiskPreparedMethod method = new BusinessRiskPreparedMethod();
        method.setMethodId("normalMethod");
        method.setSignature("public void normalMethod()");
        method.setSnippet("x".repeat(1200));
        BusinessRiskLineMap lineMap = new BusinessRiskLineMap();
        lineMap.setStartLine(1);
        lineMap.setEndLine(100);
        method.setLineMap(lineMap);

        BusinessRiskPreparedSourceFile file = new BusinessRiskPreparedSourceFile();
        file.setPath("src/main/java/com/acme/FooService.java");
        file.setMethods(List.of(method));

        BusinessRiskSourcePackage sourcePackage = new BusinessRiskSourcePackage();
        sourcePackage.setFileCount(1);
        sourcePackage.setFiles(new java.util.ArrayList<>(List.of(file)));

        BusinessRiskAnalysisHints analysisHints = new BusinessRiskAnalysisHints();
        analysisHints.setFocusMethods(new java.util.ArrayList<>(List.of("normalMethod")));

        BusinessRiskBudgetDecision decision = service.applyBudget(sourcePackage, analysisHints, 1500L);

        assertThat(decision.getDecision()).isEqualTo("TRIMMED");
        assertThat(sourcePackage.getFiles()).isEmpty();
        assertThat(decision.getDroppedFiles()).containsExactly("src/main/java/com/acme/FooService.java");
    }

    private void setField(Object target, String fieldName, Object value) throws Exception {
        Field field = target.getClass().getDeclaredField(fieldName);
        field.setAccessible(true);
        field.set(target, value);
    }
}
