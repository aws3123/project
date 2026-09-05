// k6 共享工具与测试数据
// k6 无标准 ESM/CJS，脚本内通过 open('../lib/helpers.js') + eval 方式按需加载函数。
// 说明：本文件为 k6 侧辅助函数与环境无关，不含 Node 依赖。

// ======================== 样例 diff（~5 文件 / ~300 行） ========================
// 用于多脚本复用的“典型 diff”，贴近指标3 的 ~16K token 基准描述。
function buildTypicalDiff(tag) {
  const files = [
    { p: 'UserService.java', c: 'public User getUser(Long id) {\n  if (id == null) throw new IllegalArgumentException("id");\n  return repo.findById(id);\n}' },
    { p: 'OrderService.java', c: 'for (Order o : orders) { User u = userRepo.findById(o.getUserId()); }\n// possible N+1' },
    { p: 'CacheManager.java', c: 'Product p = cache.get(key);\nif (p == null) { p = db.query(key); }\n// cache penetration risk' },
    { p: 'AccountService.java', c: 'UPDATE accounts SET balance = balance - ? WHERE id = ?\n-- no version / CAS check' },
    { p: 'TokenService.java', c: 'if (token.expireTime < now) { refreshToken(token); }\n// no lock around refresh' },
  ];
  let diff = '';
  for (let i = 0; i < files.length; i++) {
    diff += `diff --git a/${files[i].p} b/${files[i].p}\nindex abc..def 100644\n--- a/src/main/java/com/acme/${files[i].p}\n+++ b/src/main/java/com/acme/${files[i].p}\n@@ -10,8 +10,10 @@\n${files[i].c}\n`;
  }
  return diff.replace(/\$\{tag\}/g, '');
}

function traceHeaders(apiKey, prefix) {
  return {
    'X-Trace-Id': `${prefix || 'k6'}-${__VU}-${__ITER}-${Date.now()}`,
    'X-API-Key': apiKey,
    'Content-Type': 'application/json',
  };
}

// ======================== SSE 解析 ========================
// 把 SSE 字节流拆分成 [{id, event, data}]。用于指标2/3/4 的流式端点断言。
// id 字段用于指标4 的断线重连（Last-Event-ID）测试。
function parseSse(text) {
  const frames = [];
  const blocks = String(text).split('\n\n');
  for (const block of blocks) {
    if (!block) continue;
    let event = 'message';
    let data = '';
    let id = null;
    for (const line of block.split('\n')) {
      if (line.startsWith('event:')) event = line.slice(6).trim();
      else if (line.startsWith('id:')) id = line.slice(3).trim();
      else if (line.startsWith('data:')) data += line.slice(5).trim();
    }
    if (data !== '' || id !== null) frames.push({ id, event, data });
  }
  return frames;
}

module.exports = { buildTypicalDiff, traceHeaders, parseSse };