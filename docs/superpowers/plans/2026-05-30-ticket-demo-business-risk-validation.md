# Ticket Demo Business Risk Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `D:\demotest` 创建一套高信号 Java 购票源码样本，并把 `D:\AIPRO` 的业务风险审查链路修到可通过浏览器上传页完成生产级别可用的 fresh-run 验收。

**Architecture:** 样本侧只提供紧凑、可重复上传的购票源码，不追求可运行；平台侧把浏览器上传、Java 接收、预处理、dispatch gate、Python worker、任务观察与 trace 贯穿统一到一条可重复验证的链路上。为了满足“生产级别可用”，本计划会去掉客户端自带的 sessionId 变体、修正前后端 multipart/response 契约、将 Python worker 从本地 Redis 自注册切换到对 Java 的 HTTP heartbeat，并要求 Java 只在有 fresh/compatible worker 时才派发。

**Tech Stack:** React 19 + Vite + Vitest + MSW、Spring Boot 3.2 + JUnit 5 + MockMvc、FastAPI + Pydantic + pytest + httpx、SSE/EventSource、Chrome DevTools MCP。

---

**Repo note:** `git -C "D:/AIPRO" rev-parse --is-inside-work-tree` 当前失败，说明这份工作区不是 git 仓库。下面的任务用“验证 checkpoint”替代 commit；如果后续你把目录放进 git，再按每个任务末尾给出的建议消息提交。

## File Structure

### Demo sample files

- Create: `D:/demotest/TicketOrder.java` — 订单领域对象，给预处理提供稳定的票务语义
- Create: `D:/demotest/InventoryRepository.java` — 库存读写接口，显式暴露 check-then-act 风险位点
- Create: `D:/demotest/OrderRepository.java` — 订单持久化接口，显式暴露订单状态变更路径
- Create: `D:/demotest/PaymentClient.java` — 支付外部依赖，制造事务内外部调用信号
- Create: `D:/demotest/CacheClient.java` — 缓存依赖，制造 cache/db 不一致信号
- Create: `D:/demotest/CouponService.java` — 优惠券外部依赖，补强副作用路径
- Create: `D:/demotest/TicketOrderService.java` — 主热点文件，集中埋入并发、幂等、补偿、吞异常等业务风险
- Create: `D:/demotest/TicketController.java` — 入口文件，提供 controller → service 调用边

### Frontend files

- Modify: `frontend/src/api/businessRisk.ts` — 统一 multipart 字段名为重复的 `files`，而不是 `files[]`
- Modify: `frontend/src/pages/BusinessRiskSourcePage.tsx` — 去掉用户可编辑的 sessionId，统一使用服务端派生 session；把后端返回的 traceId 显示出来，并把 ApiError.traceId 拼进失败提示
- Create: `frontend/src/pages/BusinessRiskSourcePage.test.tsx` — 上传页回归测试：成功上传、文件校验、422/503 报错、traceId 显示
- Modify: `frontend/src/tests/msw/handlers.ts` — 新增 `/api/business-risk/source` multipart handler 和捕获工具
- Modify: `frontend/src/components/ReviewResultCard.tsx` — 展示 `errorCode` / `errorMessage`
- Modify: `frontend/src/pages/TaskDetailPage.tsx` — 明示 sessionId、traceId、SSE 状态与失败信息
- Modify: `frontend/src/pages/TaskDetailPage.test.tsx` — 结果错误展示、sessionId fallback、SSE 状态显示回归

### Java backend files

- Modify: `backend/src/main/java/com/acme/review/controller/BusinessRiskController.java` — 兼容 `files` / `files[]`，返回 traceId，强制服务端派生 sessionId
- Modify: `backend/src/main/java/com/acme/review/dto/BusinessRiskSourceSubmitResponse.java` — 把 `traceId` 加入提交响应
- Modify: `backend/src/main/java/com/acme/review/service/BusinessRiskTaskService.java` — `resolveSessionId` 收敛成只基于 taskId 的稳定函数
- Modify: `backend/src/main/java/com/acme/review/exception/GlobalExceptionHandler.java` — 为 `ResponseStatusException` 输出统一 ApiError 包装与 traceId
- Modify: `backend/src/main/java/com/acme/review/mq/OutboxPoller.java` — 没有 fresh/compatible worker 时一律阻断 business-risk dispatch
- Modify: `backend/src/main/java/com/acme/review/health/PythonHealthIndicator.java` — 当 discovery 开启时使用 worker registry 作为主健康源，不再“没有 heartbeat 也假装能派发”
- Modify: `backend/src/main/resources/application.yml` — 把 `python.discovery-enabled` 默认改成 `true`
- Modify: `backend/src/test/java/com/acme/review/controller/BusinessRiskControllerTest.java` — 重写为 MockMvc multipart 契约测试
- Modify: `backend/src/test/java/com/acme/review/mq/OutboxPollerTest.java` — 覆盖 no-worker block 和 successful dispatch 两条路径
- Modify: `backend/src/test/java/com/acme/review/health/PythonHealthIndicatorTest.java` — 覆盖 discovery 模式下的 cluster health

### Python worker files

- Modify: `python/config/settings.py` — 新增 heartbeat URL、token、header、worker version、max concurrency、supported versions 配置
- Create: `python/services/business_risk_worker_state.py` — 追踪 inflight_count 与 last_error，供 heartbeat payload 使用
- Modify: `python/services/business_risk_source_service.py` — 执行分析时维护 inflight_count / last_error
- Modify: `python/app/dependencies.py` — 提供共享 `BusinessRiskWorkerState` 单例
- Modify: `python/services/registry.py` — 从“写 Redis”改成“向 Java 发送 HTTP heartbeat”
- Modify: `python/app/main.py` — 生命周期里启动/停止 heartbeat sender
- Create: `python/tests/services/test_business_risk_source_service.py` — 覆盖 inflight / last_error 行为
- Create: `python/tests/services/test_registry.py` — 覆盖 heartbeat payload、header、URL、readiness 语义

---

### Task 1: Build the ticket demo source sample in `D:\demotest`

**Files:**
- Create: `D:/demotest/TicketOrder.java`
- Create: `D:/demotest/InventoryRepository.java`
- Create: `D:/demotest/OrderRepository.java`
- Create: `D:/demotest/PaymentClient.java`
- Create: `D:/demotest/CacheClient.java`
- Create: `D:/demotest/CouponService.java`
- Create: `D:/demotest/TicketOrderService.java`
- Create: `D:/demotest/TicketController.java`

- [ ] **Step 1: Create the domain object**

```java
package com.demo.ticket;

public class TicketOrder {
    private final String orderId;
    private final String userId;
    private final String showId;
    private final int ticketCount;
    private String status;

    public TicketOrder(String orderId, String userId, String showId, int ticketCount) {
        this.orderId = orderId;
        this.userId = userId;
        this.showId = showId;
        this.ticketCount = ticketCount;
        this.status = "CREATED";
    }

    public String getOrderId() {
        return orderId;
    }

    public String getUserId() {
        return userId;
    }

    public String getShowId() {
        return showId;
    }

    public int getTicketCount() {
        return ticketCount;
    }

    public String getStatus() {
        return status;
    }

    public void setStatus(String status) {
        this.status = status;
    }
}
```

- [ ] **Step 2: Create the repository and client stubs**

```java
package com.demo.ticket;

import org.springframework.stereotype.Repository;

@Repository
public class InventoryRepository {
    public int findRemaining(String showId) {
        return 5;
    }

    public void decrease(String showId, int ticketCount) {
        // intentionally non-atomic
    }

    public void increase(String showId, int ticketCount) {
        // compensation path intentionally unused by service
    }
}
```

```java
package com.demo.ticket;

import org.springframework.stereotype.Repository;

@Repository
public class OrderRepository {
    public void save(TicketOrder order) {
    }

    public void markPaid(String orderId) {
    }

    public boolean existsPaidOrder(String userId, String showId) {
        return false;
    }
}
```

```java
package com.demo.ticket;

import org.springframework.stereotype.Component;

@Component
public class PaymentClient {
    public void charge(String userId, String showId, int amountInCents) {
    }
}
```

```java
package com.demo.ticket;

import org.springframework.stereotype.Component;

@Component
public class CacheClient {
    public void put(String key, Object value) {
    }

    public void evict(String key) {
    }
}
```

```java
package com.demo.ticket;

import org.springframework.stereotype.Component;

@Component
public class CouponService {
    public void lockCoupon(String userId, String couponCode) {
    }
}
```

- [ ] **Step 3: Create the intentionally risky service hotspot**

```java
package com.demo.ticket;

import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class TicketOrderService {
    private final InventoryRepository inventoryRepository;
    private final OrderRepository orderRepository;
    private final PaymentClient paymentClient;
    private final CacheClient cacheClient;
    private final CouponService couponService;

    public TicketOrderService(
            InventoryRepository inventoryRepository,
            OrderRepository orderRepository,
            PaymentClient paymentClient,
            CacheClient cacheClient,
            CouponService couponService
    ) {
        this.inventoryRepository = inventoryRepository;
        this.orderRepository = orderRepository;
        this.paymentClient = paymentClient;
        this.cacheClient = cacheClient;
        this.couponService = couponService;
    }

    @Transactional
    public TicketOrder submitOrder(String userId, String showId, int ticketCount, String couponCode) {
        int remaining = inventoryRepository.findRemaining(showId);
        if (remaining < ticketCount) {
            throw new IllegalStateException("sold out");
        }

        TicketOrder order = new TicketOrder(UUID.randomUUID().toString(), userId, showId, ticketCount);
        orderRepository.save(order);

        couponService.lockCoupon(userId, couponCode);
        paymentClient.charge(userId, showId, ticketCount * 10000);

        inventoryRepository.decrease(showId, ticketCount);
        cacheClient.put("ticket:remaining:" + showId, remaining - ticketCount);

        try {
            orderRepository.markPaid(order.getOrderId());
            notifyDownstream(order);
        } catch (RuntimeException ex) {
            order.setStatus("PAID");
        }

        return order;
    }

    private void notifyDownstream(TicketOrder order) {
        cacheClient.put("ticket:last-order:" + order.getShowId(), order.getOrderId());
    }
}
```

- [ ] **Step 4: Create the controller entry point**

```java
package com.demo.ticket;

import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class TicketController {
    private final TicketOrderService ticketOrderService;

    public TicketController(TicketOrderService ticketOrderService) {
        this.ticketOrderService = ticketOrderService;
    }

    @PostMapping("/tickets/order")
    public TicketOrder order(
            @RequestParam String userId,
            @RequestParam String showId,
            @RequestParam int ticketCount,
            @RequestParam(required = false) String couponCode
    ) {
        return ticketOrderService.submitOrder(userId, showId, ticketCount, couponCode);
    }
}
```

- [ ] **Step 5: Verify the sample files exist**

Run: `ls "D:/demotest"/*.java`

Expected: 8 file paths, including `TicketOrderService.java` and `TicketController.java`

- [ ] **Checkpoint: note the sample is intentionally non-runnable**

Write this note into your working notes before moving on:

```text
The demo source exists only to trigger business-risk analysis. Do not spend time wiring Maven, Spring Boot startup, or a database for D:/demotest.
```

---

### Task 2: Add failing frontend tests for the browser upload flow, then make the page honor the real contract

**Files:**
- Create: `frontend/src/pages/BusinessRiskSourcePage.test.tsx`
- Modify: `frontend/src/tests/msw/handlers.ts`
- Modify: `frontend/src/api/businessRisk.ts`
- Modify: `frontend/src/pages/BusinessRiskSourcePage.tsx`
- Test: `frontend/src/pages/BusinessRiskSourcePage.test.tsx`

- [ ] **Step 1: Write the failing route-level tests**

```tsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { HttpResponse, http } from 'msw'
import { server } from '../tests/msw/server'
import { BusinessRiskSourcePage } from './BusinessRiskSourcePage'
import { getLastBusinessRiskSourceRequest, resetCapturedRequests } from '../tests/msw/handlers'

const mockedNavigate = vi.fn()

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return {
    ...actual,
    useNavigate: () => mockedNavigate,
  }
})

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/business-risk/source']}>
      <Routes>
        <Route path="/business-risk/source" element={<BusinessRiskSourcePage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('BusinessRiskSourcePage', () => {
  beforeEach(() => {
    mockedNavigate.mockReset()
    resetCapturedRequests()
  })

  it('submits selected java files through multipart and navigates to task detail', async () => {
    renderPage()

    const file = new File(['class TicketController {}'], 'TicketController.java', { type: 'text/x-java-source' })
    fireEvent.change(screen.getByLabelText('上传 .java 文件'), { target: { files: [file] } })
    fireEvent.click(screen.getByText('提交业务风险审查'))

    await waitFor(() => expect(mockedNavigate).toHaveBeenCalledWith('/tasks/biz-risk-1'))
    expect(getLastBusinessRiskSourceRequest()?.metadata.projectId).toBe('ticket-demo')
    expect(getLastBusinessRiskSourceRequest()?.files.map((item) => item.name)).toEqual(['TicketController.java'])
    expect(screen.getByText(/Trace ID：trace-biz-risk-1/)).toBeInTheDocument()
  })

  it('blocks non-java files before submit', async () => {
    renderPage()

    const file = new File(['hello'], 'notes.txt', { type: 'text/plain' })
    fireEvent.change(screen.getByLabelText('上传 .java 文件'), { target: { files: [file] } })

    expect(screen.getByText('仅支持上传 .java 文件')).toBeInTheDocument()
  })

  it('shows backend traceId when the upload fails with 503', async () => {
    server.use(
      http.post('/api/business-risk/source', async () =>
        HttpResponse.json({ message: 'worker unavailable' }, { status: 503, headers: { 'X-Trace-Id': 'trace-fail-1' } }),
      ),
    )

    renderPage()

    const file = new File(['class TicketController {}'], 'TicketController.java', { type: 'text/x-java-source' })
    fireEvent.change(screen.getByLabelText('上传 .java 文件'), { target: { files: [file] } })
    fireEvent.click(screen.getByText('提交业务风险审查'))

    expect(await screen.findByText('服务暂时不可用，请稍后重试（traceId: trace-fail-1）')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run the new test file and confirm it fails**

Run: `pnpm --dir frontend vitest run src/pages/BusinessRiskSourcePage.test.tsx`

Expected: FAIL because there is no `/api/business-risk/source` MSW handler yet and the current page does not append backend traceId to the failure text

- [ ] **Step 3: Add the multipart handler and capture helpers to MSW**

```ts
export interface CapturedBusinessRiskSourceRequest {
  metadata: {
    schemaVersion: string
    projectId: string
    repo: string
    branch: string
    requestId?: string
    traceId?: string
    entryHint?: string
  }
  files: Array<{ name: string; size: number }>
  traceId?: string | null
}

let lastBusinessRiskSourceRequest: CapturedBusinessRiskSourceRequest | null = null

export function getLastBusinessRiskSourceRequest() {
  return lastBusinessRiskSourceRequest
}

export function resetCapturedRequests() {
  lastAsyncReviewRequest = null
  lastDispatchReviewRequest = null
  lastLogRequest = null
  lastBusinessRiskSourceRequest = null
}

http.post('/api/business-risk/source', async ({ request }) => {
  const formData = await request.formData()
  const metadata = JSON.parse(String(formData.get('metadata') ?? '{}'))
  const files = formData.getAll('files').map((entry) => {
    const file = entry as File
    return { name: file.name, size: file.size }
  })

  lastBusinessRiskSourceRequest = {
    metadata,
    files,
    traceId: request.headers.get('X-Trace-Id'),
  }

  return HttpResponse.json(
    {
      taskId: 'biz-risk-1',
      status: 'PENDING',
      sessionId: 'session-biz-risk-1',
      traceId: 'trace-biz-risk-1',
      streamUrl: '/api/business-risk/stream',
    },
    { status: 202 },
  )
}),
```

- [ ] **Step 4: Standardize the upload request and remove client-controlled sessionId**

```ts
// frontend/src/api/businessRisk.ts
export function submitBusinessRiskSourceForm(input: BusinessRiskSourceUploadInput, traceId?: string) {
  const formData = new FormData()
  formData.append('metadata', JSON.stringify(input.metadata))

  for (const file of input.files) {
    formData.append('files', file)
  }

  return http<BusinessRiskSourceSubmitResponse>(SOURCE_ENDPOINT, {
    method: 'POST',
    body: formData,
    traceId,
  })
}
```

```tsx
// frontend/src/pages/BusinessRiskSourcePage.tsx
const [requestId, setRequestId] = useState('')
const [traceId, setTraceId] = useState(defaultTraceId)
const [entryHint, setEntryHint] = useState('')

const metadata: BusinessRiskSourceSubmitMetadata = {
  schemaVersion: '2.0',
  projectId,
  repo,
  branch,
  requestId: requestId || undefined,
  traceId: traceId || undefined,
  entryHint: entryHint || undefined,
}

function withTrace(message: string, submitError?: ApiError) {
  return submitError?.traceId ? `${message}（traceId: ${submitError.traceId}）` : message
}

// inside the 503 branch
setError(withTrace('服务暂时不可用，请稍后重试', submitError))

// remove the entire sessionId <div className="field"> ... </div> block from the form
```

- [ ] **Step 5: Re-run the upload page tests**

Run: `pnpm --dir frontend vitest run src/pages/BusinessRiskSourcePage.test.tsx`

Expected: PASS, including the successful upload, client-side `.java` validation, and `traceId`-decorated 503 error case

- [ ] **Checkpoint: if this repo later becomes git, use this commit message**

```text
test(frontend): cover business risk upload page contract
```

---

### Task 3: Fix the Java upload contract, response payload, deterministic sessionId, and error envelope

**Files:**
- Modify: `backend/src/main/java/com/acme/review/controller/BusinessRiskController.java`
- Modify: `backend/src/main/java/com/acme/review/dto/BusinessRiskSourceSubmitResponse.java`
- Modify: `backend/src/main/java/com/acme/review/service/BusinessRiskTaskService.java`
- Modify: `backend/src/main/java/com/acme/review/exception/GlobalExceptionHandler.java`
- Modify: `backend/src/test/java/com/acme/review/controller/BusinessRiskControllerTest.java`

- [ ] **Step 1: Rewrite the controller test around MockMvc multipart requests**

```java
@WebMvcTest(BusinessRiskController.class)
class BusinessRiskControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @MockBean
    private BusinessRiskTaskService taskService;

    @MockBean
    private BusinessRiskSseService sseService;

    @Test
    void submitReturnsTraceIdAndDeterministicSessionId() throws Exception {
        when(taskService.createTask(any(BusinessRiskSourceMetadataRequest.class))).thenReturn("biz-risk-1");
        when(taskService.resolveSessionId("biz-risk-1")).thenReturn("session-biz-risk-1");
        when(taskService.dispatchToPythonAsync(any(), any(), eq("biz-risk-1"), eq("session-biz-risk-1")))
                .thenReturn(ReviewTaskStatus.PENDING);

        mockMvc.perform(multipart("/api/business-risk/source")
                        .file(new MockMultipartFile(
                                "metadata",
                                "",
                                "application/json",
                                "{\"schemaVersion\":\"2.0\",\"projectId\":\"ticket-demo\",\"repo\":\"ticket-service\",\"branch\":\"main\"}".getBytes(StandardCharsets.UTF_8)
                        ))
                        .file(new MockMultipartFile("files", "TicketController.java", "text/x-java-source", "class TicketController {}".getBytes(StandardCharsets.UTF_8)))
                        .header("X-Trace-Id", "trace-header-1"))
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.taskId").value("biz-risk-1"))
                .andExpect(jsonPath("$.sessionId").value("session-biz-risk-1"))
                .andExpect(jsonPath("$.traceId").value("trace-header-1"));
    }

    @Test
    void submitAcceptsBracketedFilesField() throws Exception {
        when(taskService.createTask(any(BusinessRiskSourceMetadataRequest.class))).thenReturn("biz-risk-2");
        when(taskService.resolveSessionId("biz-risk-2")).thenReturn("session-biz-risk-2");
        when(taskService.dispatchToPythonAsync(any(), any(), eq("biz-risk-2"), eq("session-biz-risk-2")))
                .thenReturn(ReviewTaskStatus.PENDING);

        mockMvc.perform(multipart("/api/business-risk/source")
                        .file(new MockMultipartFile(
                                "metadata",
                                "",
                                "application/json",
                                "{\"schemaVersion\":\"2.0\",\"projectId\":\"ticket-demo\",\"repo\":\"ticket-service\",\"branch\":\"main\"}".getBytes(StandardCharsets.UTF_8)
                        ))
                        .file(new MockMultipartFile("files[]", "TicketOrderService.java", "text/x-java-source", "class TicketOrderService {}".getBytes(StandardCharsets.UTF_8))))
                .andExpect(status().isAccepted());
    }

    @Test
    void submitRejectsNonJavaFiles() throws Exception {
        mockMvc.perform(multipart("/api/business-risk/source")
                        .file(new MockMultipartFile(
                                "metadata",
                                "",
                                "application/json",
                                "{\"schemaVersion\":\"2.0\",\"projectId\":\"ticket-demo\",\"repo\":\"ticket-service\",\"branch\":\"main\"}".getBytes(StandardCharsets.UTF_8)
                        ))
                        .file(new MockMultipartFile("files", "notes.txt", "text/plain", "hello".getBytes(StandardCharsets.UTF_8))))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.message").value("only .java files are supported"));
    }
}
```

- [ ] **Step 2: Run the controller test first and confirm it fails**

Run: `cd backend && mvn test -Dtest="BusinessRiskControllerTest"`

Expected: FAIL because the current controller only binds `files`, the response DTO does not contain `traceId`, and `GlobalExceptionHandler` does not normalize `ResponseStatusException`

- [ ] **Step 3: Make the controller accept both `files` and `files[]`, and return traceId**

```java
@PostMapping(value = "/source", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
public ResponseEntity<BusinessRiskSourceSubmitResponse> submit(
        @Valid @RequestPart("metadata") BusinessRiskSourceMetadataRequest metadata,
        MultipartHttpServletRequest multipartRequest,
        @RequestHeader(value = "X-Trace-Id", required = false) String traceIdHeader
) {
    List<MultipartFile> files = resolveFiles(multipartRequest);
    validateFiles(files);

    String traceId = (metadata.getTraceId() != null && !metadata.getTraceId().isBlank())
            ? metadata.getTraceId()
            : (traceIdHeader != null && !traceIdHeader.isBlank() ? traceIdHeader : UUID.randomUUID().toString());
    metadata.setTraceId(traceId);

    String taskId = taskService.createTask(metadata);
    String sessionId = taskService.resolveSessionId(taskId);
    sseService.publish(sessionId, taskId, "task_created", "{\"status\":\"PENDING\",\"traceId\":\"" + traceId + "\"}");
    ReviewTaskStatus status = taskService.dispatchToPythonAsync(metadata, files, taskId, sessionId);

    return ResponseEntity.accepted().body(new BusinessRiskSourceSubmitResponse(
            taskId,
            status.name(),
            "/api/business-risk/stream",
            sessionId,
            traceId
    ));
}

private List<MultipartFile> resolveFiles(MultipartHttpServletRequest multipartRequest) {
    List<MultipartFile> resolved = new ArrayList<>();
    resolved.addAll(multipartRequest.getFiles("files"));
    resolved.addAll(multipartRequest.getFiles("files[]"));
    return resolved;
}
```

```java
@Getter
@AllArgsConstructor
public class BusinessRiskSourceSubmitResponse {
    private String taskId;
    private String status;
    private String streamUrl;
    private String sessionId;
    private String traceId;
}
```

- [ ] **Step 4: Force sessionId to be server-derived and deterministic**

```java
public String resolveSessionId(String taskId) {
    return "session-" + taskId;
}
```

Replace the old `resolveSessionId(BusinessRiskSourceMetadataRequest request, String taskId)` method entirely so the browser cannot send a custom value that breaks refresh/reconnect semantics.

- [ ] **Step 5: Normalize `ResponseStatusException` into the same ApiError shape**

```java
@ExceptionHandler(ResponseStatusException.class)
public ResponseEntity<ApiError> handleResponseStatusException(ResponseStatusException ex, HttpServletRequest request) {
    HttpStatus status = HttpStatus.valueOf(ex.getStatusCode().value());
    ApiError error = new ApiError(
            Instant.now(),
            status.value(),
            status.getReasonPhrase(),
            ex.getReason(),
            request.getRequestURI(),
            extractTraceId(request)
    );
    return ResponseEntity.status(status).body(error);
}
```

- [ ] **Step 6: Re-run the controller test**

Run: `cd backend && mvn test -Dtest="BusinessRiskControllerTest"`

Expected: PASS, with accepted multipart uploads, a stable `sessionId`, a returned `traceId`, and a normalized `422` error body for non-Java files

- [ ] **Checkpoint: if this repo later becomes git, use this commit message**

```text
fix(java): align business risk upload contract and response trace
```

---

### Task 4: Make the task detail page production-observable for business-risk failures and reconnects

**Files:**
- Modify: `frontend/src/components/ReviewResultCard.tsx`
- Modify: `frontend/src/pages/TaskDetailPage.tsx`
- Modify: `frontend/src/pages/TaskDetailPage.test.tsx`
- Test: `frontend/src/pages/TaskDetailPage.test.tsx`

- [ ] **Step 1: Add failing tests for sessionId fallback and result error details**

```tsx
it('shows the deterministic session id and trace id for business risk tasks', async () => {
  useTaskStore.getState().upsertTasks([
    {
      taskId: 'task-1',
      projectId: 'p1',
      status: 'PROCESSING',
      mode: 'business_risk_source',
      traceId: 'trace-local-1',
      createdAt: new Date().toISOString(),
    },
  ])

  renderPage()

  expect(await screen.findByText('摘要信息')).toBeInTheDocument()
  expect(screen.getByText('session-task-1')).toBeInTheDocument()
  expect(screen.getByTestId('trace-id-value')).toHaveTextContent('trace-from-api')
})

it('renders error code and error message when the result is failed', async () => {
  useTaskStore.getState().upsertTasks([
    {
      taskId: 'task-1',
      projectId: 'p1',
      status: 'FAILED',
      mode: 'business_risk_source',
      createdAt: new Date().toISOString(),
    },
  ])
  useResultStore.getState().setResult({
    taskId: 'task-1',
    riskScore: 0,
    riskBreakdown: [],
    needHumanReview: false,
    errorCode: 'PYTHON_WORKER_UNAVAILABLE',
    errorMessage: 'Business risk dispatch blocked: PYTHON_WORKER_UNAVAILABLE',
  })

  renderPage()

  expect(await screen.findByText('错误码：PYTHON_WORKER_UNAVAILABLE')).toBeInTheDocument()
  expect(screen.getByText('Business risk dispatch blocked: PYTHON_WORKER_UNAVAILABLE')).toBeInTheDocument()
})
```

- [ ] **Step 2: Run the task detail tests and confirm the new assertions fail**

Run: `pnpm --dir frontend vitest run src/pages/TaskDetailPage.test.tsx`

Expected: FAIL because the page does not render a sessionId fallback and `ReviewResultCard` does not show `errorCode` / `errorMessage`

- [ ] **Step 3: Show the deterministic session id in the sidebar**

```tsx
const effectiveSessionId = task?.sessionId || `session-${taskId}`

{useSseAsPrimary && (
  <p className="page-desc" data-testid="business-risk-sse-state">
    事件流连接：{sseConnected ? '已连接' : '已断开（轮询兜底中）'}
  </p>
)}

<div className="summary-row">
  <dt>Session ID</dt>
  <dd className="trace-text">{effectiveSessionId}</dd>
</div>
```

- [ ] **Step 4: Render backend error details in the result card**

```tsx
{result.errorCode && <p className="error-text">错误码：{result.errorCode}</p>}
{result.errorMessage && <p className="error-text">{result.errorMessage}</p>}
```

Put those two lines directly under the `risk-score-panel` in `ReviewResultCard.tsx` so the operator sees the business-risk failure reason without opening logs first.

- [ ] **Step 5: Re-run the task detail tests**

Run: `pnpm --dir frontend vitest run src/pages/TaskDetailPage.test.tsx`

Expected: PASS, with explicit SSE state, deterministic `session-taskId`, trace id, and backend error details visible in the UI

- [ ] **Checkpoint: if this repo later becomes git, use this commit message**

```text
feat(frontend): surface business risk observability details
```

---

### Task 5: Replace the Python worker’s local Redis self-registration with HTTP heartbeats to Java

**Files:**
- Modify: `python/config/settings.py`
- Create: `python/services/business_risk_worker_state.py`
- Modify: `python/services/business_risk_source_service.py`
- Modify: `python/app/dependencies.py`
- Modify: `python/services/registry.py`
- Modify: `python/app/main.py`
- Create: `python/tests/services/test_business_risk_source_service.py`
- Create: `python/tests/services/test_registry.py`
- Test: `python/tests/services/test_business_risk_source_service.py`
- Test: `python/tests/services/test_registry.py`

- [ ] **Step 1: Write the failing worker-state and heartbeat tests**

```python
# python/tests/services/test_business_risk_source_service.py
from unittest.mock import Mock
import pytest

from services.business_risk_source_service import BusinessRiskSourceService
from services.business_risk_worker_state import BusinessRiskWorkerState
from schemas.business_risk_review import BusinessRiskReviewRequest


def make_request() -> BusinessRiskReviewRequest:
    return BusinessRiskReviewRequest(
        run_id="run-1",
        task_id="task-1",
        project_id="ticket-demo",
        repo="ticket-service",
        branch="main",
        request_id="req-1",
        session_id="session-task-1",
        trace_id="trace-1",
        source_package={"file_count": 0, "files": [], "budget": {"decision": "ACCEPT_AS_IS", "raw_total_bytes": 0, "prepared_total_bytes": 0, "dropped_files": []}},
        metadata={},
        memory_context={},
        user_feedback_signals={},
    )


def test_service_tracks_inflight_and_last_error():
    runner = Mock()
    runner.run.side_effect = RuntimeError("llm timeout")
    state = BusinessRiskWorkerState()
    service = BusinessRiskSourceService(runner, state)

    with pytest.raises(RuntimeError, match="llm timeout"):
        service.run(make_request())

    snapshot = state.snapshot()
    assert snapshot["inflight_count"] == 0
    assert snapshot["last_error"] == "llm timeout"
```

```python
# python/tests/services/test_registry.py
import pytest

from config.settings import AppSettings
from schemas.result import BusinessRiskSourceReadinessStatus
from services.business_risk_worker_state import BusinessRiskWorkerState
from services.registry import WorkerRegistry


class StubResponse:
    def __init__(self, status_code: int = 202) -> None:
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"bad status: {self.status_code}")


class StubClient:
    def __init__(self) -> None:
        self.calls = []

    async def post(self, url, json, headers):
        self.calls.append({"url": url, "json": json, "headers": headers})
        return StubResponse(202)


@pytest.mark.asyncio
async def test_registry_posts_java_heartbeat_contract():
    client = StubClient()
    settings = AppSettings(
        llm_api_key="test-key",
        business_risk_worker_heartbeat_url="http://localhost:8080/api/internal/business-risk/worker-heartbeat",
        business_risk_worker_token="dev-callback",
        business_risk_worker_token_header="X-Worker-Token",
        business_risk_worker_version="2026.05.30",
        business_risk_worker_max_concurrency=4,
        business_risk_worker_heartbeat_interval_seconds=15,
        business_risk_schema_versions_supported="2.0,3.0",
        business_risk_java_preprocess_versions_supported="3.0",
    )
    state = BusinessRiskWorkerState()

    registry = WorkerRegistry(
        settings=settings,
        readiness_provider=lambda: BusinessRiskSourceReadinessStatus(
            overall="UP",
            route={"status": "UP", "detail": "business-risk-source readiness route registered"},
            config={"status": "UP", "detail": "llm_api_key configured"},
            persistence={"status": "UP", "detail": "stateless worker does not require task persistence"},
            llm={"status": "UP", "detail": "llm_api_key configured"},
        ),
        worker_state=state,
        client=client,
    )

    await registry.send_heartbeat_once()

    call = client.calls[0]
    assert call["url"] == "http://localhost:8080/api/internal/business-risk/worker-heartbeat"
    assert call["headers"]["X-Worker-Token"] == "dev-callback"
    assert call["json"]["readiness"] == "UP"
    assert call["json"]["inflight_count"] == 0
    assert call["json"]["schema_versions_supported"] == ["2.0", "3.0"]
    assert call["json"]["java_preprocess_versions_supported"] == ["3.0"]
```

- [ ] **Step 2: Run the new Python service tests and confirm they fail**

Run: `cd python && uv run pytest tests/services/test_business_risk_source_service.py tests/services/test_registry.py -q`

Expected: FAIL because there is no shared worker state object yet and `WorkerRegistry` still writes to Redis instead of POSTing to Java

- [ ] **Step 3: Add explicit worker heartbeat configuration**

```python
class AppSettings(BaseSettings):
    app_env: str = "dev"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    # existing fields...
    business_risk_worker_heartbeat_url: str = "http://localhost:8080/api/internal/business-risk/worker-heartbeat"
    business_risk_worker_token: str = "dev-callback"
    business_risk_worker_token_header: str = "X-Worker-Token"
    business_risk_worker_version: str = "2026.05.30"
    business_risk_worker_max_concurrency: int = 4
    business_risk_worker_heartbeat_interval_seconds: int = 15
    business_risk_schema_versions_supported: str = "2.0,3.0"
    business_risk_java_preprocess_versions_supported: str = "3.0"
```

- [ ] **Step 4: Create the worker-state helper and wrap analysis runs with it**

```python
# python/services/business_risk_worker_state.py
from __future__ import annotations

from contextlib import contextmanager
from threading import Lock


class BusinessRiskWorkerState:
    def __init__(self) -> None:
        self._lock = Lock()
        self._inflight_count = 0
        self._last_error: str | None = None

    @contextmanager
    def track_run(self):
        with self._lock:
            self._inflight_count += 1
        try:
            yield
        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)
            raise
        finally:
            with self._lock:
                self._inflight_count = max(0, self._inflight_count - 1)

    def snapshot(self) -> dict[str, int | str | None]:
        with self._lock:
            return {
                "inflight_count": self._inflight_count,
                "last_error": self._last_error,
            }
```

```python
# python/services/business_risk_source_service.py
class BusinessRiskSourceService:
    def __init__(self, runner: BusinessRiskRunner, worker_state: BusinessRiskWorkerState) -> None:
        self._runner = runner
        self._worker_state = worker_state

    def run(self, request: BusinessRiskReviewRequest) -> BusinessRiskReviewResult:
        with self._worker_state.track_run():
            return self._runner.run(request)
```

```python
# python/app/dependencies.py
_worker_state: BusinessRiskWorkerState | None = None
_worker_state_lock = RLock()


def get_business_risk_worker_state() -> BusinessRiskWorkerState:
    global _worker_state
    with _worker_state_lock:
        if _worker_state is None:
            _worker_state = BusinessRiskWorkerState()
        return _worker_state


def get_business_risk_service() -> BusinessRiskSourceService:
    settings = get_settings()
    telemetry = _resolve_telemetry(settings)
    log_service = _create_log_service(telemetry=telemetry)
    llm_client = get_llm_client()
    runner = _build_business_risk_runner(
        task_service=None,
        log_service=log_service,
        telemetry=telemetry,
        llm_client=llm_client,
    )
    return BusinessRiskSourceService(BusinessRiskRunner(runner), get_business_risk_worker_state())
```

- [ ] **Step 5: Rewrite the registry as an HTTP heartbeat sender**

```python
# python/services/registry.py
from __future__ import annotations

import asyncio
import socket
from datetime import datetime, timezone

import httpx

from config.settings import AppSettings
from services.business_risk_worker_state import BusinessRiskWorkerState


class WorkerRegistry:
    def __init__(
        self,
        settings: AppSettings,
        readiness_provider,
        worker_state: BusinessRiskWorkerState,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._readiness_provider = readiness_provider
        self._worker_state = worker_state
        self._client = client or httpx.AsyncClient(timeout=5.0)
        self._running = False
        self._instance_id = f"{socket.gethostname()}:{settings.app_port}"
        self._started_at = datetime.now(timezone.utc).isoformat()

    async def send_heartbeat_once(self) -> None:
        readiness = self._readiness_provider()
        snapshot = self._worker_state.snapshot()
        payload = {
            "instance_id": self._instance_id,
            "worker_version": self._settings.business_risk_worker_version,
            "started_at": self._started_at,
            "schema_versions_supported": [item.strip() for item in self._settings.business_risk_schema_versions_supported.split(',') if item.strip()],
            "java_preprocess_versions_supported": [item.strip() for item in self._settings.business_risk_java_preprocess_versions_supported.split(',') if item.strip()],
            "readiness": readiness.overall,
            "inflight_count": snapshot["inflight_count"],
            "max_concurrency": self._settings.business_risk_worker_max_concurrency,
            "last_error": snapshot["last_error"],
        }
        headers = {
            self._settings.business_risk_worker_token_header: self._settings.business_risk_worker_token,
            "X-Trace-Id": f"worker-heartbeat-{self._instance_id}",
        }
        response = await self._client.post(self._settings.business_risk_worker_heartbeat_url, json=payload, headers=headers)
        response.raise_for_status()

    async def heartbeat_loop(self) -> None:
        self._running = True
        while self._running:
            try:
                await self.send_heartbeat_once()
                await asyncio.sleep(self._settings.business_risk_worker_heartbeat_interval_seconds)
            except Exception:
                await asyncio.sleep(5)

    async def unregister(self) -> None:
        self._running = False
        await self._client.aclose()
```

- [ ] **Step 6: Start the new sender from the FastAPI lifespan**

```python
# python/app/main.py
from app.dependencies import get_business_risk_source_readiness, get_business_risk_worker_state, get_settings

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _registry, _registry_task
    settings = get_settings()
    app.state.settings = settings

    _registry = WorkerRegistry(
        settings=settings,
        readiness_provider=get_business_risk_source_readiness,
        worker_state=get_business_risk_worker_state(),
    )
    _registry_task = asyncio.create_task(_registry.heartbeat_loop())
    logger.info("WorkerRegistry heartbeat sender started instance=%s", _registry._instance_id)

    yield

    if _registry is not None:
        await _registry.unregister()
    if _registry_task is not None:
        _registry_task.cancel()
```

- [ ] **Step 7: Re-run the Python service tests**

Run: `cd python && uv run pytest tests/services/test_business_risk_source_service.py tests/services/test_registry.py -q`

Expected: PASS, with a heartbeat payload that matches Java’s DTO contract and a service that drives `inflight_count` / `last_error`

- [ ] **Checkpoint: if this repo later becomes git, use this commit message**

```text
feat(python): send business risk worker heartbeats to java
```

---

### Task 6: Make Java dispatch and health checks depend on fresh compatible worker heartbeats

**Files:**
- Modify: `backend/src/main/java/com/acme/review/mq/OutboxPoller.java`
- Modify: `backend/src/main/java/com/acme/review/health/PythonHealthIndicator.java`
- Modify: `backend/src/main/resources/application.yml`
- Modify: `backend/src/test/java/com/acme/review/mq/OutboxPollerTest.java`
- Modify: `backend/src/test/java/com/acme/review/health/PythonHealthIndicatorTest.java`

- [ ] **Step 1: Write failing Java tests for no-worker blocking and discovery health**

```java
@Test
void shouldBlockBusinessRiskDispatchWhenNoCompatibleWorkersExist() {
    OutboxEvent event = new OutboxEvent();
    event.setEventId("e-block-1");
    event.setAggregateId("task-block-1");
    event.setEventType("BUSINESS_RISK_DISPATCH");
    event.setStatus("PENDING");
    event.setRetryCount(9);
    event.setPayload("{\"task_id\":\"task-block-1\",\"session_id\":\"session-task-block-1\",\"trace_id\":\"trace-block-1\",\"schema_version\":\"2.0\",\"java_preprocess_version\":\"3.0\"}");

    when(workerRegistryService.snapshot("2.0", "3.0")).thenReturn(blockedSnapshot("PYTHON_WORKER_UNAVAILABLE"));

    poller.sendEvent(event);

    verify(businessRiskTaskService).markBusinessRiskDispatchFailed(
            "task-block-1",
            "session-task-block-1",
            "trace-block-1",
            "PYTHON_WORKER_UNAVAILABLE",
            "Business risk dispatch blocked: PYTHON_WORKER_UNAVAILABLE"
    );
    assertThat(event.getStatus()).isEqualTo("DEAD");
}
```

```java
@Test
void shouldReportDownWhenDiscoveryIsEnabledAndNoWorkerIsReady() {
    PythonHealthIndicator indicator = new PythonHealthIndicator(webClient, properties, workerRegistryService, metricsService);
    properties.setDiscoveryEnabled(true);
    when(workerRegistryService.snapshot()).thenReturn(blockedSnapshot("PYTHON_WORKER_UNAVAILABLE"));

    Health health = indicator.health();

    assertThat(health.getStatus().getCode()).isEqualTo("DOWN");
    assertThat(health.getDetails()).containsEntry("reason", "PYTHON_WORKER_UNAVAILABLE");
}
```

Add a small helper inside both test files:

```java
private BusinessRiskWorkerRegistrySnapshot blockedSnapshot(String reason) {
    BusinessRiskWorkerRegistrySnapshot snapshot = new BusinessRiskWorkerRegistrySnapshot();
    snapshot.setActiveWorkers(0);
    snapshot.setReadyWorkers(0);
    snapshot.setAvailableSlots(0);
    snapshot.setDispatchAllowed(false);
    snapshot.setBlockReason(reason);
    return snapshot;
}
```

- [ ] **Step 2: Run the two Java test files and confirm they fail**

Run: `cd backend && mvn test -Dtest="OutboxPollerTest,PythonHealthIndicatorTest"`

Expected: FAIL because `OutboxPoller` still dispatches when `activeWorkers == 0`, and `PythonHealthIndicatorTest` still uses the old constructor/behavior

- [ ] **Step 3: Block dispatch whenever the registry says dispatch is not allowed**

```java
BusinessRiskWorkerRegistrySnapshot snapshot = workerRegistryService.snapshot(request.getSchemaVersion(), request.getJavaPreprocessVersion());
metricsService.recordWorkerSnapshot(snapshot);
if (!snapshot.isDispatchAllowed()) {
    metricsService.recordDispatchBlocked(snapshot.getBlockReason());
    throw new BusinessRiskDispatchGateException(
            snapshot.getBlockReason(),
            "Business risk dispatch blocked: " + snapshot.getBlockReason()
    );
}
```

Replace the old `if (snapshot.getActiveWorkers() > 0 && !snapshot.isDispatchAllowed())` branch with this exact check.

- [ ] **Step 4: Make Python health discovery-first when enabled**

```java
@Override
public Health health() {
    if (pythonClientProperties.isDiscoveryEnabled()) {
        BusinessRiskWorkerRegistrySnapshot snapshot = workerRegistryService.snapshot();
        metricsService.recordWorkerSnapshot(snapshot);
        if (snapshot.isDispatchAllowed()) {
            return Health.up()
                    .withDetail("activeWorkers", snapshot.getActiveWorkers())
                    .withDetail("readyWorkers", snapshot.getReadyWorkers())
                    .withDetail("availableSlots", snapshot.getAvailableSlots())
                    .withDetail("staleWorkers", snapshot.getStaleWorkers())
                    .build();
        }
        return Health.down()
                .withDetail("activeWorkers", snapshot.getActiveWorkers())
                .withDetail("readyWorkers", snapshot.getReadyWorkers())
                .withDetail("availableSlots", snapshot.getAvailableSlots())
                .withDetail("staleWorkers", snapshot.getStaleWorkers())
                .withDetail("reason", snapshot.getBlockReason())
                .build();
    }

    String path = pythonClientProperties.getBusinessRiskHealthPath();
    // keep the existing HTTP fallback block unchanged below this point
}
```

- [ ] **Step 5: Turn discovery on by default for this backend**

```yml
python:
  base-url: ${PYTHON_BASE_URL:http://localhost:8000}
  sync-path: ${PYTHON_SYNC_PATH:/ai/review/sync}
  logs-path: ${PYTHON_LOGS_PATH:/ai/review/logs}
  timeout-ms: ${PYTHON_TIMEOUT_MS:60000}
  connect-timeout-ms: 3000
  discovery-enabled: ${PYTHON_DISCOVERY_ENABLED:true}
  health-path: ${PYTHON_HEALTH_PATH:/ai/health}
  business-risk-health-path: ${PYTHON_BUSINESS_RISK_HEALTH_PATH:/ai/health/business-risk-source}
```

- [ ] **Step 6: Re-run the Java dispatch/health tests**

Run: `cd backend && mvn test -Dtest="OutboxPollerTest,PythonHealthIndicatorTest"`

Expected: PASS, with dispatch blocked when no worker heartbeat exists and actuator health reporting `DOWN` until a compatible worker is alive

- [ ] **Checkpoint: if this repo later becomes git, use this commit message**

```text
fix(java): gate business risk dispatch on live worker heartbeats
```

---

### Task 7: Re-run the focused automated suites before touching the browser

**Files:**
- Verify only — no source changes expected here

- [ ] **Step 1: Run the frontend business-risk regression suite**

Run: `pnpm --dir frontend vitest run src/pages/BusinessRiskSourcePage.test.tsx src/pages/TaskDetailPage.test.tsx src/hooks/useBusinessRiskSse.test.ts`

Expected: PASS

- [ ] **Step 2: Run the Java business-risk regression suite**

Run: `cd backend && mvn test -Dtest="BusinessRiskControllerTest,OutboxPollerTest,PythonHealthIndicatorTest"`

Expected: PASS

- [ ] **Step 3: Run the Python business-risk regression suite**

Run: `cd python && uv run pytest tests/app/test_business_risk_source_route.py tests/app/test_business_risk_source_readiness_route.py tests/services/test_business_risk_source_service.py tests/services/test_registry.py -q`

Expected: PASS

- [ ] **Step 4: If any suite fails, stop and fix the owning task first**

Use this rule exactly:

```text
Frontend failure -> return to Task 2 or Task 4.
Java failure -> return to Task 3 or Task 6.
Python failure -> return to Task 5.
Do not continue to browser verification with red tests.
```

---

### Task 8: Start the full chain and verify health before opening the browser

**Files:**
- Verify only — no source changes expected here

- [ ] **Step 1: Confirm a usable LLM API key already exists in this shell**

Run: `python - <<'PY'
import os
print('present' if os.getenv('LLM_API_KEY') else 'missing')
PY`

Expected: `present`

- [ ] **Step 2: Start the Python worker with heartbeat enabled**

Run: `cd python && LLM_API_KEY="$LLM_API_KEY" uv run uvicorn app.main:app --host 0.0.0.0 --port 8000`

Expected: server starts on `http://localhost:8000`, and logs include `WorkerRegistry heartbeat sender started`

- [ ] **Step 3: Start the Java backend with discovery enabled**

Run: `/d/develop/apache-maven-3.9.4/bin/mvn -f backend/pom.xml spring-boot:run -Dmaven.test.skip=true`

Expected: Spring Boot starts on `http://localhost:8080`, and `/actuator/health` eventually reports the `python` component as `UP`

- [ ] **Step 4: Start the frontend**

Run: `pnpm --dir frontend dev`

Expected: Vite starts and prints a local URL such as `http://localhost:5173`

- [ ] **Step 5: Verify Python readiness directly**

Run: `curl -i http://localhost:8000/ai/health/business-risk-source`

Expected: HTTP `200` and response body contains `"overall":"UP"`

- [ ] **Step 6: Verify Java sees a live worker**

Run: `curl -i http://localhost:8080/actuator/health`

Expected: HTTP `200` and response body contains a `python` component with `"status":"UP"`

---

### Task 9: Execute the browser-based fresh-run validation loop until the chain is production-grade usable

**Files:**
- Verify only — this task uses the browser and existing logs/endpoints

- [ ] **Step 1: Upload the demo through the browser entry point**

Open: `http://localhost:5173/business-risk/source`

Then perform these exact browser actions:

```text
1. Keep the default projectId=token-demo? No — overwrite it with projectId=ticket-demo.
2. Keep repo=ticket-service and branch=main.
3. Upload all .java files from D:/demotest.
4. Click “提交业务风险审查”.
5. Wait for navigation to /tasks/<taskId>.
```

Expected: the page shows a task detail view with visible `Trace ID`, visible `Session ID`, and an SSE status line (`已连接` or `已断开（轮询兜底中）`).

- [ ] **Step 2: Record the three identifiers from the UI**

Write down these exact values from the task page before doing anything else:

```text
taskId = <value shown in the sidebar>
sessionId = <value shown in the sidebar>
traceId = <value shown in the sidebar>
```

Expected: all three values are present and non-empty

- [ ] **Step 3: Refresh the task page once**

Browser action:

```text
Press reload once while the task is still visible.
```

Expected: the page stays on the same task, still shows the same `traceId`, still shows `session-<taskId>` as the session id, and resumes live observation through SSE or polling fallback

- [ ] **Step 4: Verify the final result is specific, not generic**

Wait for terminal state, then check the result card.

Expected: the result mentions multiple ticketing risks, not a generic summary. At minimum, the report or summary should clearly reflect at least three of these themes:

```text
库存超卖 / 并发竞态
重复下单 / 幂等缺失
事务内外部调用
缓存与持久化不一致
补偿缺失 / 异常吞掉
```

- [ ] **Step 5: Verify the failure path is also diagnosable**

Do one deliberate negative run:

```text
1. Stop the Python process.
2. Submit the same D:/demotest files again from the browser.
3. Observe the failure text on the upload page or task page.
4. Restart Python.
5. Submit one more fresh run.
```

Expected:

```text
- With Python down, the failure is visible and includes a diagnostic reason such as PYTHON_WORKER_UNAVAILABLE or a 503-style worker message.
- After Python restarts, Java health returns to UP.
- A fresh browser upload succeeds again without manual DB cleanup.
```

- [ ] **Step 6: Verify the trace line through logs**

Use the identifiers from Step 2 and check each layer’s logs.

Run these read-only checks in separate terminals:

```text
Frontend terminal: look for the browser upload request and the Vite proxy call.
Java terminal: search visually for the exact traceId from Step 2 in request/dispatch/callback logs.
Python terminal: search visually for the same traceId in /ai/business-risk/source handling logs.
```

Expected: the same `traceId` is visible in frontend-generated request headers, Java processing logs, and Python analysis logs

- [ ] **Step 7: Decide whether the chain is production-grade usable**

Use this gate exactly:

```text
YES only if:
- browser upload works on a fresh run
- no-worker mode fails fast and visibly
- a restarted worker can recover the next fresh run
- refresh/reconnect does not lose the task
- traceId is usable across all three layers
- the report is ticket-risk specific

NO if any one of those bullets fails.
```

- [ ] **Step 8: If the answer is NO, loop back to the owning task and fix the root cause**

Use this mapping exactly:

```text
Upload page / multipart / trace text -> Task 2 or Task 3
Task detail / refresh / SSE / polling fallback -> Task 4
Heartbeat sender / worker readiness -> Task 5
No-worker dispatch / health mismatch -> Task 6
Generic or weak business-risk output -> Task 1 first, then re-run Task 9
```

- [ ] **Checkpoint: if this repo later becomes git, use this commit message**

```text
feat(validation): make business risk review chain production-grade usable
```

---

## Self-Review Checklist

- Spec coverage:
  - demo sample creation -> Task 1
  - browser upload entry point -> Tasks 2, 3, 9
  - timeout/reconnect/observability -> Tasks 4, 8, 9
  - production-grade heartbeat/discovery -> Tasks 5, 6, 8, 9
  - “fix until usable” loop -> Task 9 steps 7-8
- Placeholder scan:
  - no `TODO`, `TBD`, or “similar to above” markers remain
- Type consistency:
  - frontend upload uses repeated `files`
  - controller accepts `files` and `files[]`
  - Java response includes `traceId`
  - session id becomes deterministic `session-<taskId>` everywhere
  - Python heartbeat payload matches `BusinessRiskWorkerHeartbeatRequest`
