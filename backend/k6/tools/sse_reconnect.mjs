/** Native Node 20+ SSE verifier: 300 streams, deterministic 10% abort/reconnect, event-ID completeness. */
const base = process.env.TARGET_URL || 'http://localhost:8080';
const runId = process.env.RUN_ID;
const apiKey = process.env.API_KEY || 'dev-key';
const header = process.env.API_KEY_HEADER || 'X-API-Key';
const total = Number(process.env.SSE_TASKS || 300);
const disconnectPercent = Number(process.env.SSE_DISCONNECT_PERCENT || 10);
if (!runId) throw new Error('RUN_ID is required; seed tasks with k6 using the same RUN_ID.');

const headers = { [header]: apiKey, Accept: 'text/event-stream' };
async function taskIds() {
  const ids = [];
  for (let page = 1; ids.length < total; page++) {
    const r = await fetch(`${base}/api/review/tasks?page=${page}&size=100&projectId=perf-${encodeURIComponent(runId)}`, { headers: { [header]: apiKey } });
    if (!r.ok) throw new Error(`task query failed: ${r.status}`);
    const body = await r.json(); ids.push(...(body.items || []).map(x => x.taskId));
    if (!body.items?.length) break;
  }
  if (ids.length < total) throw new Error(`Expected ${total} tasks, found ${ids.length}`);
  return ids.slice(0, total);
}
function parse(frame) {
  const out = {}; for (const line of frame.split(/\r?\n/)) { const i = line.indexOf(':'); if (i > 0) out[line.slice(0, i)] = line.slice(i + 1).trim(); }
  return out;
}
async function consume(id, disconnect) {
  const names = new Set(); const ids = new Set(); let lastId = ''; let reconnectMs = null;
  async function open(reconnect) {
    const ac = new AbortController(); const h = { ...headers }; if (lastId) h['Last-Event-ID'] = lastId;
    const opened = performance.now(); const r = await fetch(`${base}/api/review/tasks/${id}/stream`, { headers: h, signal: ac.signal });
    if (!r.ok || !r.body) throw new Error(`stream ${id}: ${r.status}`);
    const reader = r.body.getReader(); const decoder = new TextDecoder(); let buffer = ''; let aborted = false;
    while (true) {
      const { value, done } = await reader.read(); if (done) return;
      buffer += decoder.decode(value, { stream: true });
      let cut; while ((cut = buffer.indexOf('\n\n')) >= 0) {
        const event = parse(buffer.slice(0, cut)); buffer = buffer.slice(cut + 2);
        if (!event.id) continue;
        if (reconnect && reconnectMs === null) reconnectMs = performance.now() - opened;
        ids.add(event.id); lastId = event.id; names.add(event.event || 'message');
        if (disconnect && !aborted) { aborted = true; ac.abort(); return; }
        if (event.event === 'result' || event.event === 'task_failed') return;
      }
    }
  }
  try { await open(false); if (disconnect) await open(true); }
  catch (e) { if (!String(e.name).includes('Abort')) throw e; if (disconnect) await open(true); }
  const complete = names.has('status') && (names.has('result') || names.has('task_failed'));
  return { complete, disconnected: disconnect, reconnectMs, events: ids.size };
}
const ids = await taskIds();
const results = await Promise.all(ids.map((id, i) => consume(id, i % Math.round(100 / disconnectPercent) === 0)));
const cut = results.filter(x => x.disconnected); const complete = results.filter(x => x.complete).length;
const latencies = cut.map(x => x.reconnectMs).filter(Number.isFinite);
const out = { connections: total, disconnected: cut.length, completionRatio: complete / total,
  avgReconnectMs: latencies.reduce((a, b) => a + b, 0) / (latencies.length || 1),
  minEvents: Math.min(...results.map(x => x.events)) };
console.log(JSON.stringify(out));
if (out.completionRatio !== 1 || cut.length !== Math.round(total * disconnectPercent / 100)) process.exit(1);
