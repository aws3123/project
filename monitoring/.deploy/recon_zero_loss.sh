#!/bin/bash
# 零丢失对账：k6 提交 taskIds vs review_task DB（用 mysql 客户端，避免 python 依赖）
LOG="/opt/review/k6/run_burst_pool200.log"
MYSQL=(mysql -h127.0.0.1 -P3306 -ureview -previewdb123 -N review)

echo "=== 1. 从 k6 日志提取 taskId ==="
grep -oE 'taskId\\":\\"[a-zA-Z0-9-]+\\"' "$LOG" | sed -E 's/.*taskId\\":\\"([a-zA-Z0-9-]+)\\".*/\1/' | sort -u > /opt/review/k6_ids_unique.txt
grep -oE 'taskId\\":\\"[a-zA-Z0-9-]+\\"' "$LOG" | sed -E 's/.*taskId\\":\\"([a-zA-Z0-9-]+)\\".*/\1/' > /opt/review/k6_ids_all.txt
echo "k6 log taskId 提交次数(含重试): $(wc -l </opt/review/k6_ids_all.txt)"
echo "k6 log taskId 去重: $(wc -l </opt/review/k6_ids_unique.txt)"

echo ""
echo "=== 2. DB 全量统计 ==="
echo -n "review_task 总行数: "; "${MYSQL[@]}" -e "SELECT COUNT(*) FROM review_task;"
echo -n "review_task task_id 重复组: "; "${MYSQL[@]}" -e "SELECT COUNT(*) FROM (SELECT task_id FROM review_task GROUP BY task_id HAVING COUNT(*)>1) t;"
echo -n "review_result task_id 重复组: "; "${MYSQL[@]}" -e "SELECT COUNT(*) FROM (SELECT task_id FROM review_result GROUP BY task_id HAVING COUNT(*)>1) t;"

echo ""
echo "=== 3. k6 提交 vs DB 缺失核对 ==="
"${MYSQL[@]}" -e "DROP TEMPORARY TABLE IF EXISTS tmp_k6;" 2>/dev/null
"${MYSQL[@]}" -e "CREATE TEMPORARY TABLE tmp_k6(task_id VARCHAR(128) PRIMARY KEY);"
while IFS= read -r id; do
  [ -n "$id" ] && "${MYSQL[@]}" -e "INSERT IGNORE INTO tmp_k6 VALUES('$id');"
done < /opt/review/k6_ids_unique.txt

echo -n "k6 提交但 DB 缺失(missing_in_db): "
"${MYSQL[@]}" -e "SELECT COUNT(*) FROM tmp_k6 k LEFT JOIN review_task t ON k.task_id=t.task_id WHERE t.task_id IS NULL;"
echo -n "DB 中不在 k6 日志(存量/其它): "
"${MYSQL[@]}" -e "SELECT COUNT(*) FROM review_task t LEFT JOIN tmp_k6 k ON t.task_id=k.task_id WHERE k.task_id IS NULL;"
"${MYSQL[@]}" -e "DROP TEMPORARY TABLE tmp_k6;" 2>/dev/null

echo ""
echo "=== 4. k6 这批任务的终态分布 ==="
"${MYSQL[@]}" -e "CREATE TEMPORARY TABLE tmp_k6a(task_id VARCHAR(128) PRIMARY KEY);"
while IFS= read -r id; do
  [ -n "$id" ] && "${MYSQL[@]}" -e "INSERT IGNORE INTO tmp_k6a VALUES('$id');"
done < /opt/review/k6_ids_unique.txt
"${MYSQL[@]}" -e "SELECT t.status, COUNT(*) AS cnt FROM tmp_k6a k JOIN review_task t ON k.task_id=t.task_id GROUP BY t.status ORDER BY cnt DESC;"
"${MYSQL[@]}" -e "SELECT COUNT(*) AS not_terminal FROM tmp_k6a k JOIN review_task t ON k.task_id=t.task_id WHERE t.status NOT IN ('SUCCESS','HUMAN_REVIEW','FAILED');"
"${MYSQL[@]}" -e "DROP TEMPORARY TABLE tmp_k6a;" 2>/dev/null

echo ""
echo "=== 5. 压测时间窗增量（created_at 证据） ==="
"${MYSQL[@]}" -e "SELECT DATE_FORMAT(created_at,'%H:%i') h, COUNT(*) FROM review_task WHERE created_at BETWEEN '2026-09-16 02:00:00' AND '2026-09-16 02:30:00' GROUP BY h ORDER BY h;"