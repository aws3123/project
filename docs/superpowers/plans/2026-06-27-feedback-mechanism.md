# 点踩反馈闭环 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现前端点踩功能 + Java API 落库 + 反馈统计数据导出，完成"收集"环节。

**Architecture:** 前端 `FeedbackWidget` 组件嵌入 `TaskDetailPage`，提交 POST 到 Java `FeedbackController` → `FeedbackService` → `FeedbackMapper` 写入 MySQL `user_feedback` 表。Java 端同时提供统计和导出 API 供 Python 分析管道使用。k6 脚本验证 200 并发性能目标。

**Tech Stack:** Java 17 + Spring Boot 3.2 + MyBatis-Plus, React + TypeScript + Zustand, k6

---

## 文件结构

| 操作 | 文件 | 说明 |
|------|------|------|
| 修改 | `backend/src/main/resources/schema.sql` | 追加 `user_feedback` 表 DDL |
| 新建 | `backend/.../entity/UserFeedback.java` | MyBatis-Plus 实体 |
| 新建 | `backend/.../repository/mapper/FeedbackMapper.java` | MyBatis-Plus Mapper |
| 新建 | `backend/.../service/FeedbackService.java` | 业务逻辑：提交、统计、导出 |
| 新建 | `backend/.../controller/FeedbackController.java` | REST 端点 |
| 新建 | `backend/.../service/FeedbackServiceTest.java` | Service 单元测试 |
| 新建 | `backend/.../controller/FeedbackControllerTest.java` | Controller 集成测试 |
| 新建 | `frontend/src/types/feedback.ts` | 类型定义 |
| 新建 | `frontend/src/api/feedback.ts` | API 函数 |
| 新建 | `frontend/src/components/FeedbackWidget.tsx` | 点踩组件 |
| 修改 | `frontend/src/pages/TaskDetailPage.tsx` | 嵌入 FeedbackWidget |
| 修改 | `frontend/src/tests/msw/handlers.ts` | 追加反馈 mock handler |
| 新建 | `frontend/src/components/FeedbackWidget.test.tsx` | 组件测试 |
| 新建 | `k6/feedback-submit.js` | 压测脚本 |

---

### Task 1: 数据库 DDL — user_feedback 表

**Files:**
- Modify: `backend/src/main/resources/schema.sql`

- [ ] **Step 1: 在 schema.sql 末尾追加 user_feedback 表 DDL**

将以下 DDL 追加到 `schema.sql` 文件末尾：

```sql
-- ==========================================
-- 用户反馈表: 点踩闭环数据收集
-- ==========================================
CREATE TABLE IF NOT EXISTS user_feedback (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    task_id VARCHAR(64) NOT NULL COMMENT '关联任务 ID',
    session_id VARCHAR(128) NOT NULL COMMENT '会话 ID',
    feedback_type VARCHAR(16) NOT NULL COMMENT 'thumbs_up|thumbs_down',
    category VARCHAR(32) DEFAULT NULL COMMENT '结果准确|结果不准确|遗漏风险|误报|其他',
    comment TEXT DEFAULT NULL COMMENT '用户选填文本意见',
    metadata JSON DEFAULT NULL COMMENT '检索文档、相关度分数、系统回答等',
    user_agent VARCHAR(256) DEFAULT NULL,
    source VARCHAR(32) DEFAULT 'review' COMMENT 'review|business_risk',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    INDEX idx_feedback_task (task_id),
    INDEX idx_feedback_session (session_id),
    INDEX idx_feedback_type_created (feedback_type, created_at)
);
```

- [ ] **Step 2: 验证 SQL 语法**

不需要测试，只是 DDL 追加。

- [ ] **Step 3: Commit**

---

### Task 2: Java Entity — UserFeedback

**Files:**
- Create: `backend/src/main/java/com/acme/review/entity/UserFeedback.java`

- [ ] **Step 1: 创建 UserFeedback 实体**

```java
package com.acme.review.entity;

import com.baomidou.mybatisplus.annotation.FieldFill;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.Instant;

@Data
@NoArgsConstructor
@TableName("user_feedback")
public class UserFeedback {

    @TableId(type = IdType.AUTO)
    private Long id;

    @TableField("task_id")
    private String taskId;

    @TableField("session_id")
    private String sessionId;

    @TableField("feedback_type")
    private String feedbackType;

    @TableField("category")
    private String category;

    @TableField("comment")
    private String comment;

    @TableField("metadata")
    private String metadata;

    @TableField("user_agent")
    private String userAgent;

    @TableField("source")
    private String source;

    @TableField(value = "created_at", fill = FieldFill.INSERT)
    private Instant createdAt;
}
```

- [ ] **Step 2: Commit**

---

### Task 3: Java Mapper — FeedbackMapper

**Files:**
- Create: `backend/src/main/java/com/acme/review/repository/mapper/FeedbackMapper.java`

- [ ] **Step 1: 创建 FeedbackMapper**

```java
package com.acme.review.repository.mapper;

import com.acme.review.entity.UserFeedback;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.time.Instant;
import java.util.List;
import java.util.Map;

@Mapper
public interface FeedbackMapper extends BaseMapper<UserFeedback> {

    @Select("SELECT feedback_type, COUNT(*) AS cnt FROM user_feedback " +
            "WHERE created_at >= #{from} AND created_at <= #{to} " +
            "AND (#{source} IS NULL OR source = #{source}) " +
            "GROUP BY feedback_type")
    List<Map<String, Object>> countByType(@Param("from") Instant from,
                                          @Param("to") Instant to,
                                          @Param("source") String source);

    @Select("SELECT DATE(created_at) AS day, feedback_type, COUNT(*) AS cnt FROM user_feedback " +
            "WHERE created_at >= #{from} AND created_at <= #{to} " +
            "AND (#{source} IS NULL OR source = #{source}) " +
            "GROUP BY DATE(created_at), feedback_type " +
            "ORDER BY day ASC")
    List<Map<String, Object>> dailyBreakdown(@Param("from") Instant from,
                                             @Param("to") Instant to,
                                             @Param("source") String source);
}
```

- [ ] **Step 2: Commit**

---

### Task 4: Java Service — FeedbackService

**Files:**
- Create: `backend/src/main/java/com/acme/review/service/FeedbackService.java`

- [ ] **Step 1: 创建 FeedbackService**

```java
package com.acme.review.service;

import com.acme.review.entity.UserFeedback;
import com.acme.review.repository.mapper.FeedbackMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
@Slf4j
public class FeedbackService {

    private static final long MAX_METADATA_BYTES = 65535;

    private final FeedbackMapper feedbackMapper;
    private final ObjectMapper objectMapper;

    /**
     * 提交反馈。同一 taskId + sessionId 时幂等更新（保留最近一次）。
     */
    public UserFeedback submit(UserFeedback feedback) {
        if (feedback.getMetadata() != null && feedback.getMetadata().length() > MAX_METADATA_BYTES) {
            feedback.setMetadata(feedback.getMetadata().substring(0, (int) MAX_METADATA_BYTES));
        }

        // 幂等：同一 taskId + sessionId + feedbackType 更新已有记录
        List<UserFeedback> existing = feedbackMapper.selectList(
                new LambdaQueryWrapper<UserFeedback>()
                        .eq(UserFeedback::getTaskId, feedback.getTaskId())
                        .eq(UserFeedback::getSessionId, feedback.getSessionId())
                        .eq(UserFeedback::getFeedbackType, feedback.getFeedbackType())
                        .orderByDesc(UserFeedback::getId)
                        .last("LIMIT 1")
        );

        if (!existing.isEmpty()) {
            UserFeedback prev = existing.get(0);
            feedback.setId(prev.getId());
            if (feedback.getCreatedAt() == null) {
                feedback.setCreatedAt(Instant.now());
            }
            feedbackMapper.updateById(feedback);
            log.debug("Updated feedback id={} taskId={} type={}", feedback.getId(), feedback.getTaskId(), feedback.getFeedbackType());
            return feedback;
        }

        if (feedback.getCreatedAt() == null) {
            feedback.setCreatedAt(Instant.now());
        }
        feedbackMapper.insert(feedback);
        log.debug("Created feedback id={} taskId={} type={}", feedback.getId(), feedback.getTaskId(), feedback.getFeedbackType());
        return feedback;
    }

    /**
     * 获取反馈统计。
     */
    public Map<String, Object> getStats(Instant from, Instant to, String source) {
        List<Map<String, Object>> typeCounts = feedbackMapper.countByType(from, to, source);
        long total = 0;
        long thumbsUp = 0;
        long thumbsDown = 0;
        for (Map<String, Object> row : typeCounts) {
            String type = (String) row.get("feedback_type");
            Number cnt = (Number) row.get("cnt");
            long count = cnt != null ? cnt.longValue() : 0;
            total += count;
            if ("thumbs_up".equals(type)) thumbsUp = count;
            else if ("thumbs_down".equals(type)) thumbsDown = count;
        }

        List<Map<String, Object>> dailyRows = feedbackMapper.dailyBreakdown(from, to, source);
        List<Map<String, Object>> dailyBreakdown = dailyRows.stream()
                .collect(Collectors.groupingBy(r -> (String) r.get("day"),
                        LinkedHashMap::new,
                        Collectors.toMap(
                                r -> (String) r.get("feedback_type"),
                                r -> ((Number) r.get("cnt")).longValue(),
                                (a, b) -> a,
                                LinkedHashMap::new
                        )))
                .entrySet().stream()
                .map(entry -> {
                    Map<String, Object> dayMap = new LinkedHashMap<>();
                    dayMap.put("date", entry.getKey());
                    dayMap.put("thumbs_up", entry.getValue().getOrDefault("thumbs_up", 0L));
                    dayMap.put("thumbs_down", entry.getValue().getOrDefault("thumbs_down", 0L));
                    return dayMap;
                })
                .collect(Collectors.toList());

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("total", total);
        result.put("thumbs_up", thumbsUp);
        result.put("thumbs_down", thumbsDown);
        result.put("ratio", total > 0 ? String.format("%.2f", (double) thumbsUp / total) : "0.00");
        result.put("daily_breakdown", dailyBreakdown);
        return result;
    }

    /**
     * 导出反馈明细（分页）。
     */
    public IPage<UserFeedback> export(Instant from, Instant to, String source, int page, int size) {
        Page<UserFeedback> pageObj = new Page<>(page, size);
        LambdaQueryWrapper<UserFeedback> wrapper = new LambdaQueryWrapper<UserFeedback>()
                .between(UserFeedback::getCreatedAt, from, to)
                .orderByDesc(UserFeedback::getCreatedAt);
        if (source != null && !source.isBlank()) {
            wrapper.eq(UserFeedback::getSource, source);
        }
        return feedbackMapper.selectPage(pageObj, wrapper);
    }
}
```

- [ ] **Step 2: Commit**

---

### Task 5: Java Controller — FeedbackController

**Files:**
- Create: `backend/src/main/java/com/acme/review/controller/FeedbackController.java`

- [ ] **Step 1: 创建 FeedbackController**

```java
package com.acme.review.controller;

import com.acme.review.entity.UserFeedback;
import com.acme.review.service.FeedbackService;
import com.baomidou.mybatisplus.core.metadata.IPage;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import lombok.Data;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;

@RestController
@RequestMapping("/api/feedback")
@Validated
@RequiredArgsConstructor
public class FeedbackController {

    private final FeedbackService feedbackService;

    @Data
    public static class SubmitRequest {
        @NotBlank(message = "taskId is required")
        private String taskId;

        @NotBlank(message = "sessionId is required")
        private String sessionId;

        @NotBlank(message = "feedbackType is required")
        @Pattern(regexp = "thumbs_up|thumbs_down", message = "feedbackType must be thumbs_up or thumbs_down")
        private String feedbackType;

        private String category;
        private String comment;
        private String metadata;
        private String source;
    }

    @PostMapping("/submit")
    public ResponseEntity<Map<String, Object>> submitFeedback(
            @Valid @RequestBody SubmitRequest request,
            @RequestHeader(value = HttpHeaders.USER_AGENT, required = false) String userAgent) {

        UserFeedback feedback = new UserFeedback();
        feedback.setTaskId(request.getTaskId());
        feedback.setSessionId(request.getSessionId());
        feedback.setFeedbackType(request.getFeedbackType());
        feedback.setCategory(request.getCategory());
        feedback.setComment(request.getComment());
        feedback.setMetadata(request.getMetadata());
        feedback.setUserAgent(userAgent);
        feedback.setSource(request.getSource() != null ? request.getSource() : "review");

        UserFeedback saved = feedbackService.submit(feedback);

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("id", saved.getId());
        body.put("status", "accepted");
        return ResponseEntity.status(HttpStatus.CREATED).body(body);
    }

    @GetMapping("/stats")
    public ResponseEntity<Map<String, Object>> getStats(
            @RequestParam @jakarta.validation.constraints.PastOrPresent Instant from,
            @RequestParam Instant to,
            @RequestParam(required = false) String source) {
        return ResponseEntity.ok(feedbackService.getStats(from, to, source));
    }

    @GetMapping("/export")
    public ResponseEntity<IPage<UserFeedback>> export(
            @RequestParam @jakarta.validation.constraints.PastOrPresent Instant from,
            @RequestParam Instant to,
            @RequestParam(required = false) String source,
            @RequestParam(defaultValue = "1") @Min(1) int page,
            @RequestParam(defaultValue = "50") @Min(1) @Max(1000) int size) {
        return ResponseEntity.ok(feedbackService.export(from, to, source, page, size));
    }
}
```

- [ ] **Step 2: Commit**

---

### Task 6: Java Service Test — FeedbackServiceTest

**Files:**
- Create: `backend/src/test/java/com/acme/review/service/FeedbackServiceTest.java`

- [ ] **Step 1: 写入测试**

```java
package com.acme.review.service;

import com.acme.review.entity.UserFeedback;
import com.acme.review.repository.mapper.FeedbackMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class FeedbackServiceTest {

    private FeedbackMapper feedbackMapper;
    private FeedbackService service;

    @BeforeEach
    void setUp() {
        feedbackMapper = mock(FeedbackMapper.class);
        service = new FeedbackService(feedbackMapper, new ObjectMapper());
    }

    @Test
    void shouldInsertNewFeedback() {
        UserFeedback feedback = new UserFeedback();
        feedback.setTaskId("task-1");
        feedback.setSessionId("session-1");
        feedback.setFeedbackType("thumbs_down");

        when(feedbackMapper.selectList(any())).thenReturn(List.of());
        when(feedbackMapper.insert(any())).thenReturn(1);

        UserFeedback saved = service.submit(feedback);

        assertThat(saved.getTaskId()).isEqualTo("task-1");
        assertThat(saved.getFeedbackType()).isEqualTo("thumbs_down");
        verify(feedbackMapper).insert(any());
    }

    @Test
    void shouldUpdateExistingFeedbackForSameTaskAndSession() {
        UserFeedback existing = new UserFeedback();
        existing.setId(1L);
        existing.setTaskId("task-1");
        existing.setSessionId("session-1");
        existing.setFeedbackType("thumbs_up");

        UserFeedback newFeedback = new UserFeedback();
        newFeedback.setTaskId("task-1");
        newFeedback.setSessionId("session-1");
        newFeedback.setFeedbackType("thumbs_up");
        newFeedback.setCategory("误报");

        when(feedbackMapper.selectList(any())).thenReturn(List.of(existing));

        UserFeedback saved = service.submit(newFeedback);

        assertThat(saved.getId()).isEqualTo(1L);
        assertThat(saved.getCategory()).isEqualTo("误报");
        verify(feedbackMapper).updateById(any());
        verify(feedbackMapper, never()).insert(any());
    }

    @Test
    void shouldTruncateOversizedMetadata() {
        UserFeedback feedback = new UserFeedback();
        feedback.setTaskId("task-1");
        feedback.setSessionId("session-1");
        feedback.setFeedbackType("thumbs_up");
        feedback.setMetadata("x".repeat(70000));

        when(feedbackMapper.selectList(any())).thenReturn(List.of());

        service.submit(feedback);

        assertThat(feedback.getMetadata().length()).isLessThanOrEqualTo(65535);
    }

    @Test
    void shouldGetStats() {
        Instant from = Instant.parse("2026-06-01T00:00:00Z");
        Instant to = Instant.parse("2026-06-27T00:00:00Z");

        when(feedbackMapper.countByType(eq(from), eq(to), eq(null)))
                .thenReturn(List.of(
                        Map.of("feedback_type", "thumbs_up", "cnt", 30L),
                        Map.of("feedback_type", "thumbs_down", "cnt", 10L)
                ));
        when(feedbackMapper.dailyBreakdown(eq(from), eq(to), eq(null)))
                .thenReturn(List.of(
                        Map.of("day", "2026-06-01", "feedback_type", "thumbs_up", "cnt", 5L),
                        Map.of("day", "2026-06-01", "feedback_type", "thumbs_down", "cnt", 2L)
                ));

        Map<String, Object> stats = service.getStats(from, to, null);

        assertThat(stats.get("total")).isEqualTo(40L);
        assertThat(stats.get("thumbs_up")).isEqualTo(30L);
        assertThat(stats.get("thumbs_down")).isEqualTo(10L);
        assertThat(stats.get("ratio")).isEqualTo("0.75");
        assertThat(stats.get("daily_breakdown")).isInstanceOf(List.class);
    }

    @Test
    void shouldExportFeedback() {
        Instant from = Instant.parse("2026-06-01T00:00:00Z");
        Instant to = Instant.parse("2026-06-27T00:00:00Z");

        Page<UserFeedback> mockPage = new Page<>(1, 10);
        UserFeedback fb = new UserFeedback();
        fb.setId(1L);
        fb.setTaskId("task-1");
        fb.setFeedbackType("thumbs_up");
        mockPage.setRecords(List.of(fb));
        mockPage.setTotal(1);

        when(feedbackMapper.selectPage(any(Page.class), any())).thenReturn(mockPage);

        IPage<UserFeedback> result = service.export(from, to, "review", 1, 10);
        assertThat(result.getRecords()).hasSize(1);
        assertThat(result.getRecords().get(0).getTaskId()).isEqualTo("task-1");
    }
}
```

- [ ] **Step 2: 运行测试验证通过**

Run: `cd backend && mvn test -Dtest="FeedbackServiceTest"`
Expected: BUILD SUCCESS

- [ ] **Step 3: Commit**

---

### Task 7: Java Controller Test — FeedbackControllerTest

**Files:**
- Create: `backend/src/test/java/com/acme/review/controller/FeedbackControllerTest.java`

- [ ] **Step 1: 写入测试**

```java
package com.acme.review.controller;

import com.acme.review.config.ApiAuthenticationEntryPoint;
import com.acme.review.config.ApiKeyAuthenticationFilter;
import com.acme.review.config.SecurityConfig;
import com.acme.review.config.SecurityProperties;
import com.acme.review.entity.UserFeedback;
import com.acme.review.repository.mapper.FeedbackMapper;
import com.acme.review.service.FeedbackService;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import java.time.Instant;
import java.util.List;
import java.util.Map;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(controllers = FeedbackController.class)
@AutoConfigureMockMvc
@Import({SecurityConfig.class, FeedbackControllerTest.SecurityTestConfig.class})
class FeedbackControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @MockBean
    private FeedbackService feedbackService;

    @MockBean
    private FeedbackMapper feedbackMapper;

    private final ObjectMapper objectMapper = new ObjectMapper();

    @Test
    void shouldSubmitFeedbackAndReturn201() throws Exception {
        Map<String, Object> body = Map.of(
                "taskId", "task-1",
                "sessionId", "session-1",
                "feedbackType", "thumbs_up"
        );

        UserFeedback saved = new UserFeedback();
        saved.setId(1L);
        saved.setTaskId("task-1");
        saved.setSessionId("session-1");
        saved.setFeedbackType("thumbs_up");

        when(feedbackService.submit(any())).thenReturn(saved);

        mockMvc.perform(post("/api/feedback/submit")
                        .header("X-API-Key", "test-key")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(body)))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.id").value(1))
                .andExpect(jsonPath("$.status").value("accepted"));
    }

    @Test
    void shouldRejectMissingTaskId() throws Exception {
        Map<String, Object> body = Map.of(
                "sessionId", "session-1",
                "feedbackType", "thumbs_up"
        );

        mockMvc.perform(post("/api/feedback/submit")
                        .header("X-API-Key", "test-key")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(body)))
                .andExpect(status().isBadRequest());
    }

    @Test
    void shouldRejectInvalidFeedbackType() throws Exception {
        Map<String, Object> body = Map.of(
                "taskId", "task-1",
                "sessionId", "session-1",
                "feedbackType", "invalid"
        );

        mockMvc.perform(post("/api/feedback/submit")
                        .header("X-API-Key", "test-key")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(body)))
                .andExpect(status().isBadRequest());
    }

    @Test
    void shouldReturnStats() throws Exception {
        when(feedbackService.getStats(any(), any(), eq(null)))
                .thenReturn(Map.of("total", 40L, "thumbs_up", 30L, "thumbs_down", 10L, "ratio", "0.75", "daily_breakdown", List.of()));

        mockMvc.perform(get("/api/feedback/stats")
                        .header("X-API-Key", "test-key")
                        .param("from", "2026-06-01T00:00:00Z")
                        .param("to", "2026-06-27T00:00:00Z"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.total").value(40))
                .andExpect(jsonPath("$.ratio").value("0.75"));
    }

    @Test
    void shouldExportFeedback() throws Exception {
        UserFeedback fb = new UserFeedback();
        fb.setId(1L);
        fb.setTaskId("task-1");
        fb.setFeedbackType("thumbs_up");
        IPage<UserFeedback> page = new Page<>(1, 10, 1);
        page.setRecords(List.of(fb));

        when(feedbackService.export(any(), any(), eq("review"), eq(1), eq(10)))
                .thenReturn(page);

        mockMvc.perform(get("/api/feedback/export")
                        .header("X-API-Key", "test-key")
                        .param("from", "2026-06-01T00:00:00Z")
                        .param("to", "2026-06-27T00:00:00Z")
                        .param("source", "review")
                        .param("page", "1")
                        .param("size", "10"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.records[0].taskId").value("task-1"));
    }

    @Test
    void shouldReturnUnauthorizedWhenHeaderMissing() throws Exception {
        mockMvc.perform(get("/api/feedback/stats")
                        .param("from", "2026-06-01T00:00:00Z")
                        .param("to", "2026-06-27T00:00:00Z"))
                .andExpect(status().isUnauthorized());
    }

    @TestConfiguration
    static class SecurityTestConfig {
        @Bean
        SecurityProperties securityProperties() {
            return new SecurityProperties("X-API-Key", "test-key", "callback-token");
        }

        @Bean
        ApiAuthenticationEntryPoint apiAuthenticationEntryPoint() {
            return new ApiAuthenticationEntryPoint();
        }

        @Bean
        ApiKeyAuthenticationFilter apiKeyAuthenticationFilter(SecurityProperties securityProperties) {
            return new ApiKeyAuthenticationFilter(securityProperties);
        }
    }
}
```

- [ ] **Step 2: 运行测试验证通过**

Run: `cd backend && mvn test -Dtest="FeedbackControllerTest"`
Expected: BUILD SUCCESS

- [ ] **Step 3: 运行全部后端测试确保无回归**

Run: `cd backend && mvn test`
Expected: BUILD SUCCESS

- [ ] **Step 4: Commit**

---

### Task 8: 前端 Types — feedback.ts

**Files:**
- Create: `frontend/src/types/feedback.ts`

- [ ] **Step 1: 写入类型定义**

```typescript
export type FeedbackType = 'thumbs_up' | 'thumbs_down'

export type FeedbackCategory =
  | '结果准确'
  | '结果不准确'
  | '遗漏风险'
  | '误报'
  | '其他'

export interface FeedbackSubmitRequest {
  taskId: string
  sessionId: string
  feedbackType: FeedbackType
  category?: FeedbackCategory | string
  comment?: string
  metadata?: string  // JSON string, 含 retrievedDocs/relevanceScores/systemAnswer
  source?: 'review' | 'business_risk'
}

export interface FeedbackSubmitResponse {
  id: number
  status: 'accepted'
}

export interface FeedbackState {
  submitted: boolean
  type?: FeedbackType
  category?: string
  comment?: string
}

export const FEEDBACK_CATEGORIES: { value: FeedbackCategory; label: string }[] = [
  { value: '结果准确', label: '结果准确' },
  { value: '结果不准确', label: '结果不准确' },
  { value: '遗漏风险', label: '遗漏了风险' },
  { value: '误报', label: '误报/非风险' },
  { value: '其他', label: '其他' },
]
```

- [ ] **Step 2: Commit**

---

### Task 9: 前端 API — api/feedback.ts

**Files:**
- Create: `frontend/src/api/feedback.ts`

- [ ] **Step 1: 写入 API 函数**

```typescript
import type { FeedbackSubmitRequest, FeedbackSubmitResponse } from '../types/feedback'
import { http } from './client'

export function submitFeedback(payload: FeedbackSubmitRequest, traceId?: string) {
  return http<FeedbackSubmitResponse>('/api/feedback/submit', {
    method: 'POST',
    body: JSON.stringify(payload),
    traceId,
  })
}
```

- [ ] **Step 2: 确保已存在 client.ts 的 http 函数可用**

不需要额外操作，`client.ts` 已经提供 `http<T>()` 通用函数。

- [ ] **Step 3: Commit**

---

### Task 10: 前端 MSW Handler — feedback mock

**Files:**
- Modify: `frontend/src/tests/msw/handlers.ts`

- [ ] **Step 1: 追加 feedback mock handler**

在 `handlers.ts` 末尾，`export const handlers` 数组中追加：

```typescript
// 在最后一个 handler (handoff) 之后追加:

http.post('/api/feedback/submit', async ({ request }) => {
  const body = await request.json() as { taskId: string; feedbackType: string }
  lastFeedbackRequest = { taskId: body.taskId, feedbackType: body.feedbackType }

  return HttpResponse.json(
    { id: 1, status: 'accepted' },
    { status: 201 },
  )
}),
```

同时，在文件顶部 `resetCapturedRequests` 函数附近追加相关类型和变量：

```typescript
// 追加到 existingCaptured 类型附近:
export interface CapturedFeedbackRequest {
  taskId: string
  feedbackType: string
}

// 追加到 existing lastXxx 变量附近:
let lastFeedbackRequest: CapturedFeedbackRequest | null = null

// 追加 getter:
export function getLastFeedbackRequest() {
  return lastFeedbackRequest
}

// 在 resetCapturedRequests() 中追加:
export function resetCapturedRequests() {
  // ... existing code ...
  lastFeedbackRequest = null  // <-- 追加此行
}
```

- [ ] **Step 2: Commit**

---

### Task 11: 前端组件 — FeedbackWidget

**Files:**
- Create: `frontend/src/components/FeedbackWidget.tsx`

- [ ] **Step 1: 写入组件**

```tsx
import { useState, useCallback } from 'react'
import type { FeedbackType, FeedbackCategory, FeedbackState } from '../types/feedback'
import { FEEDBACK_CATEGORIES } from '../types/feedback'
import { submitFeedback } from '../api/feedback'
import { getOrCreateTraceId } from '../utils/trace'

interface FeedbackWidgetProps {
  taskId: string
  sessionId: string
  source?: 'review' | 'business_risk'
  systemAnswer?: string   // JSON string of risk summary + details
  className?: string
}

export function FeedbackWidget({ taskId, sessionId, source = 'review', systemAnswer, className = '' }: FeedbackWidgetProps) {
  const [state, setState] = useState<FeedbackState>({ submitted: false })
  const [selectedType, setSelectedType] = useState<FeedbackType | null>(null)
  const [category, setCategory] = useState<string>('')
  const [comment, setComment] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleTypeSelect = useCallback((type: FeedbackType) => {
    if (state.submitted) return
    setSelectedType(type)
  }, [state.submitted])

  const handleSubmit = useCallback(async () => {
    if (!selectedType || submitting) return

    setSubmitting(true)
    setError(null)

    try {
      const metadata = systemAnswer
        ? JSON.stringify({ systemAnswer })
        : undefined

      await submitFeedback({
        taskId,
        sessionId,
        feedbackType: selectedType,
        category: category || undefined,
        comment: comment || undefined,
        metadata,
        source,
      }, getOrCreateTraceId())

      setState({ submitted: true, type: selectedType, category, comment })
    } catch (err) {
      setError(err instanceof Error ? err.message : '提交反馈失败')
    } finally {
      setSubmitting(false)
    }
  }, [selectedType, submitting, systemAnswer, taskId, sessionId, category, comment, source])

  if (state.submitted) {
    return (
      <div className={`feedback-widget ${className}`} data-testid="feedback-submitted">
        <p className="feedback-thanks">感谢反馈！</p>
      </div>
    )
  }

  return (
    <div className={`feedback-widget ${className}`} data-testid="feedback-widget">
      <div className="feedback-prompt">这个结果对您有帮助吗？</div>

      <div className="feedback-buttons">
        <button
          className={`feedback-btn${selectedType === 'thumbs_up' ? ' active up' : ''}`}
          onClick={() => handleTypeSelect('thumbs_up')}
          data-testid="feedback-thumbs-up"
          disabled={state.submitted}
        >
          👍 有帮助
        </button>
        <button
          className={`feedback-btn${selectedType === 'thumbs_down' ? ' active down' : ''}`}
          onClick={() => handleTypeSelect('thumbs_down')}
          data-testid="feedback-thumbs-down"
          disabled={state.submitted}
        >
          👎 没帮助
        </button>
      </div>

      {selectedType && (
        <div className="feedback-detail" data-testid="feedback-detail">
          <select
            className="feedback-category"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            data-testid="feedback-category"
          >
            <option value="">选择分类（可选）</option>
            {FEEDBACK_CATEGORIES.map((c) => (
              <option key={c.value} value={c.value}>{c.label}</option>
            ))}
          </select>

          <textarea
            className="feedback-comment"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="补充意见（可选）"
            rows={3}
            data-testid="feedback-comment"
          />

          <button
            className="feedback-submit-btn"
            onClick={handleSubmit}
            disabled={submitting}
            data-testid="feedback-submit-btn"
          >
            {submitting ? '提交中…' : '提交反馈'}
          </button>

          {error && <p className="error-text" data-testid="feedback-error">{error}</p>}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Commit**

---

### Task 12: 前端组件测试 — FeedbackWidget.test.tsx

**Files:**
- Create: `frontend/src/components/FeedbackWidget.test.tsx`

- [ ] **Step 1: 写入组件测试**

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { FeedbackWidget } from './FeedbackWidget'

const server = setupServer(
  http.post('/api/feedback/submit', async () => {
    return HttpResponse.json({ id: 1, status: 'accepted' }, { status: 201 })
  }),
)

beforeAll(() => server.listen())
afterEach(() => server.resetHandlers())
afterAll(() => server.close())

describe('FeedbackWidget', () => {
  const defaultProps = {
    taskId: 'task-1',
    sessionId: 'session-1',
  }

  it('renders prompt and buttons', () => {
    render(<FeedbackWidget {...defaultProps} />)
    expect(screen.getByText('这个结果对您有帮助吗？')).toBeInTheDocument()
    expect(screen.getByTestId('feedback-thumbs-up')).toBeInTheDocument()
    expect(screen.getByTestId('feedback-thumbs-down')).toBeInTheDocument()
  })

  it('shows detail form after selecting thumbs up', () => {
    render(<FeedbackWidget {...defaultProps} />)
    fireEvent.click(screen.getByTestId('feedback-thumbs-up'))
    expect(screen.getByTestId('feedback-detail')).toBeInTheDocument()
    expect(screen.getByTestId('feedback-category')).toBeInTheDocument()
    expect(screen.getByTestId('feedback-comment')).toBeInTheDocument()
    expect(screen.getByTestId('feedback-submit-btn')).toBeInTheDocument()
  })

  it('submits feedback and shows thanks message', async () => {
    render(<FeedbackWidget {...defaultProps} />)
    fireEvent.click(screen.getByTestId('feedback-thumbs-down'))
    fireEvent.click(screen.getByTestId('feedback-submit-btn'))

    await waitFor(() => {
      expect(screen.getByTestId('feedback-submitted')).toBeInTheDocument()
      expect(screen.getByText('感谢反馈！')).toBeInTheDocument()
    })
  })

  it('submits with category and comment', async () => {
    let capturedBody: any = null
    server.use(
      http.post('/api/feedback/submit', async ({ request }) => {
        capturedBody = await request.json()
        return HttpResponse.json({ id: 1, status: 'accepted' }, { status: 201 })
      }),
    )

    render(<FeedbackWidget {...defaultProps} />)
    fireEvent.click(screen.getByTestId('feedback-thumbs-down'))
    fireEvent.change(screen.getByTestId('feedback-category'), { target: { value: '遗漏风险' } })
    fireEvent.change(screen.getByTestId('feedback-comment'), { target: { value: '漏了一个关键 issue' } })
    fireEvent.click(screen.getByTestId('feedback-submit-btn'))

    await waitFor(() => {
      expect(capturedBody).toMatchObject({
        taskId: 'task-1',
        feedbackType: 'thumbs_down',
        category: '遗漏风险',
        comment: '漏了一个关键 issue',
      })
    })
  })

  it('shows error on submit failure', async () => {
    server.use(
      http.post('/api/feedback/submit', async () => {
        return HttpResponse.json({ message: 'server error' }, { status: 500 })
      }),
    )

    render(<FeedbackWidget {...defaultProps} />)
    fireEvent.click(screen.getByTestId('feedback-thumbs-up'))
    fireEvent.click(screen.getByTestId('feedback-submit-btn'))

    await waitFor(() => {
      expect(screen.getByTestId('feedback-error')).toBeInTheDocument()
    })
  })
})
```

- [ ] **Step 2: 运行测试验证通过**

Run: `pnpm --dir frontend vitest run src/components/FeedbackWidget.test.tsx`
Expected: PASS

- [ ] **Step 3: Commit**

---

### Task 13: 嵌入 TaskDetailPage

**Files:**
- Modify: `frontend/src/pages/TaskDetailPage.tsx`

- [ ] **Step 1: 导入 FeedbackWidget**

在文件顶部 import 区域追加：

```typescript
import { FeedbackWidget } from '../components/FeedbackWidget'
```

- [ ] **Step 2: 在 ReviewResultCard 下方嵌入 FeedbackWidget**

找到 `<ReviewResultCard result={result} />` 所在的位置（约 182 行附近），在其后追加：

```tsx
{result && (
  <div className="panel">
    <FeedbackWidget
      taskId={taskId}
      sessionId={effectiveSessionId}
      source={task?.mode === 'business_risk_source' ? 'business_risk' : 'review'}
      systemAnswer={JSON.stringify({
        riskSummary: result.riskSummary,
        details: result.details,
      })}
    />
  </div>
)}
```

嵌入位置在 `<ReviewResultCard>` 所在的 panel 之后（即 `result` 卡片后面，紧接 FeedbackWidget 的独立 panel）。

- [ ] **Step 3: 确认系统不报错**

Run: `pnpm --dir frontend build`
Expected: SUCCESS，无类型/编译错误

- [ ] **Step 4: Commit**

---

### Task 14: k6 压测脚本

**Files:**
- Create: `k6/feedback-submit.js`

- [ ] **Step 1: 写入 k6 脚本**

```javascript
import http from 'k6/http'
import { check, sleep } from 'k6'
import { SharedArray } from 'k6/data'

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8080'
const API_KEY = __ENV.API_KEY || 'dev-api-key'

const sessions = new SharedArray('sessions', () => {
  return Array.from({ length: 200 }, (_, i) => ({
    taskId: `k6-task-${i}`,
    sessionId: `k6-session-${i}`,
  }))
})

export const options = {
  stages: [
    { duration: '10s', target: 200 },  //  ramp up
    { duration: '3m', target: 200 },   //  steady
    { duration: '10s', target: 0 },    //  ramp down
  ],
  thresholds: {
    http_req_failed: ['rate<0.005'],   // 成功率 > 99.5%
    http_req_duration: ['p(99)<120'],   // P99 < 120ms
  },
}

const TYPES = ['thumbs_up', 'thumbs_down']
const CATEGORIES = ['', '结果准确', '结果不准确', '遗漏风险', '误报', '其他']

export default function () {
  const idx = (__VU - 1) % sessions.length
  const { taskId, sessionId } = sessions[idx]
  const feedbackType = TYPES[Math.floor(Math.random() * TYPES.length)]
  const category = CATEGORIES[Math.floor(Math.random() * CATEGORIES.length)]

  const payload = JSON.stringify({
    taskId,
    sessionId,
    feedbackType,
    category: category || undefined,
    comment: 'k6 load test feedback',
    source: 'review',
    metadata: JSON.stringify({
      systemAnswer: 'k6 test result summary',
      retrievedDocs: ['doc-1', 'doc-2'],
      relevanceScores: [0.95, 0.82],
    }),
  })

  const params = {
    headers: {
      'Content-Type': 'application/json',
      'X-API-Key': API_KEY,
    },
  }

  const res = http.post(`${BASE_URL}/api/feedback/submit`, payload, params)

  check(res, {
    'status is 201': (r) => r.status === 201,
    'has id field': (r) => JSON.parse(r.body).id !== undefined,
    'has accepted status': (r) => JSON.parse(r.body).status === 'accepted',
  })

  sleep(Math.random() * 0.5)  // 0~500ms 思考间隔模拟真实用户
}
```

- [ ] **Step 2: 验证脚本语法**

Run: `k6 run --dry-run k6/feedback-submit.js`
Expected: script syntax validated

- [ ] **Step 3: Commit**

---

## Spec 对照检查

| Spec 要求 | Task 覆盖 |
|-----------|-----------|
| user_feedback 表 DDL | Task 1 |
| Java Entity + Mapper | Task 2, 3 |
| FeedbackService 提交/幂等/统计/导出 | Task 4 |
| POST /api/feedback/submit | Task 5 |
| GET /api/feedback/stats | Task 5 |
| GET /api/feedback/export | Task 5 |
| 前端 FeedbackWidget 组件 | Task 11 |
| 前端 TaskDetailPage 嵌入 | Task 13 |
| 前端提交 → 后端落库完整链路 | Task 5, 9, 11 |
| Java 单元+集成测试 | Task 6, 7 |
| 前端单元测试 | Task 12 |
| k6 压测脚本 | Task 14 |
| metadata 携带 systemAnswer/检索信息 | Task 11, 14 |
| 幂等（同一 taskId + sessionId 更新） | Task 4 |
