package com.acme.review.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.util.ArrayList;
import java.util.List;

@Getter
@Setter
@NoArgsConstructor
public class BusinessRiskPreparedSourceFile {

    private String path;

    @JsonProperty("package_name")
    private String packageName;

    @JsonProperty("class_name")
    private String className;

    @JsonProperty("class_annotations")
    private List<String> classAnnotations = new ArrayList<>();

    private List<String> interfaces = new ArrayList<>();

    @JsonProperty("repository_dependencies")
    private List<String> repositoryDependencies = new ArrayList<>();

    @JsonProperty("external_dependencies")
    private List<String> externalDependencies = new ArrayList<>();

    private List<BusinessRiskPreparedMethod> methods = new ArrayList<>();

    private List<BusinessRiskPreparedHotspot> hotspots = new ArrayList<>();
}
