// k6 统一配置
// 用法：其他脚本通过 JSON.parse(open('../config.js')) 加载
//
// 环境变量覆盖：
//   BASE_URL    Java BFF 地址（默认 http://localhost:8080）
//   PY_BASE_URL Python 服务地址（默认 http://localhost:8000）
//   API_KEY     认证 Key（默认 dev-key）
//
// ⚠️ 压测口径（与「面试指标与结果」文件夹统一）：
//   - 架构层压测使用 mock LLM（延迟由校准层真实采样标定），
//     验证对象是架构本身（GIL/前置/扩展/削峰/对账），与 LLM 真假无关。
//   - 所有"声称值"（42/202/4.8×/24s→5s/40%/3000积压/30s恢复）均为待实测锚点，
//     脚本产出实测值后回填简历与 QA 文件。

module.exports = {
  // ======================== 服务端点 ========================
  baseUrl: __ENV.BASE_URL || 'http://localhost:8080',
  pyBaseUrl: __ENV.PY_BASE_URL || 'http://localhost:8000',
  apiKey: __ENV.API_KEY || 'dev-key',

  // Java BFF 内部接口（prefix 已在 controller 定义）
  endpoints: {
    // —— 同步 / 流式 / 异步 / 分发 / 任务 ——
    sync: '/api/review/sync',             // POST → 200 ReviewSyncResponse
    syncStream: '/api/review/sync/stream',// POST → SSE(run_started..run_finished)
    async: '/api/review/async',           // POST → 202 ReviewAsyncResponse{taskId,status}
    dispatch: '/api/review/dispatch',     // POST → 200 ReviewDispatchResponse
    taskById: '/api/review/tasks',        // GET  /{taskId} → TaskDetailResponse{task,result}
    // —— SSE 断线重连（NotificationController，支持 Last-Event-ID 头/参数） ——
    taskStream: '/api/review/tasks',      // GET  /{taskId}/stream → SSE(Redis快照+增量追平)
    // —— AST 解析（CPU 密集前置到 Java） ——
    chunk: '/api/internal/chunk',         // POST → CodeChunkResult{totalChunks}
    // —— 反馈闭环 ——
    feedbackSubmit: '/api/feedback/submit', // POST → 201 {id,status:"accepted"}
    feedbackStats: '/api/feedback/stats', //  GET ?from&to&source
  },

  // 常见复用字段（无需改动，供各脚本按需取用）
  headers: {
    'Content-Type': 'application/json',
  },

  // ======================== 压测阶段 ========================
  // 五条指标对应的推荐压测参数（统一口径，均为"待实测基准"）
  stages: {
    // 指标1: 分层解耦端到端吞吐对比
    //   口径：k6 1000 VU / 5min，baseline(Python单实例直连) vs optimized(BFF+多实例)
    //   Little's Law 验证：平均延迟 = 1000 ÷ 实测吞吐（预期 baseline≈24s / optimized≈5s）
    throughput: { vu: 1000, duration: '5m' },
    // 指标2: 多Agent 并行 vs 串行延迟对比（SSE step durationMs 累加 vs 端到端实测）
    latencyCompare: { vu: 30, duration: '5m' },
    // 指标3: 上下文工程（合规率实测；token/成本由 BillingAspect DB 聚合产出）
    contextQuality: { vu: 50, duration: '3m' },
    // 指标4: 异步高可用（两段式）
    //   稳态：constant-arrival-rate 200 req/s × 30min（消费能力设计值 4×250信号量÷5s）→ 零死信
    //   突发：ramping-vus 至 500 并发压受理层（瞬时 ~1500 QPS，DB 容量内）→ 积压+30s恢复+零丢失
    asyncStableRate: 200,          // req/s（到达速率，非并发数）
    asyncStableDuration: '30m',
    asyncBurstTarget: 500,         // 突发并发峰值
    // 指标5: 反馈闭环
    feedback: { vu: 200, duration: '3m' },
  },

  // ======================== 成本计价（指标3） ========================
  // DeepSeek deepseek-v4-flash 峰值价（折算人民币 元/1M token，可被环境变量覆盖）
  //   预期锚点：16K token(≈12K入+4K出) → 12K×3.2/M + 4K×9.5/M ≈ ¥0.076/次
  pricing: {
    inputPerMillion: Number(__ENV.COST_INPUT || 3.2),   // 元 / 1M 输入 token
    outputPerMillion: Number(__ENV.COST_OUTPUT || 9.5), // 元 / 1M 输出 token
    // 输入/输出拆分比例（token 总量 × 该比例拆算成本）
    inputRatio: 0.75,   // 12K/16K
    outputRatio: 0.25,  // 4K/16K
  },

  // ======================== 全局阈值 ========================
  thresholds: {
    httpReqOK: ['http_req_failed<0.02', 'http_reqs>=0'],
  },
};
