#!/bin/bash
# 压测专用：以禁用 API 限流的方式重启后端，用于 3000 VU 突发零丢失验证
cd /opt/review/backend
pkill -f 'review-backend-0.0.1'
sleep 4
ps -ef | grep '[r]eview-backend' || echo OLD_KILLED
export SPRING_PROFILES_ACTIVE=dev SERVER_PORT=8080 MANAGEMENT_HEALTH_RABBIT_ENABLED=false
export SPRING_DATASOURCE_URL='jdbc:mysql://localhost:3306/review?useSSL=false&allowPublicKeyRetrieval=true&serverTimezone=UTC&characterEncoding=UTF-8&connectionCollation=utf8mb4_unicode_ci'
export SPRING_DATASOURCE_USERNAME=review SPRING_DATASOURCE_PASSWORD=reviewdb123
export REDIS_HOST=localhost REDIS_PORT=6379
export PYTHON_BASE_URL=http://localhost:8000
export SPRING_CLOUD_STREAM_KAFKA_BINDER_BROKERS=localhost:9092 MQ_BINDER=kafka
export API_KEY=dev-key CALLBACK_TOKEN=dev-callback
export MINIO_ENDPOINT=http://localhost:9000 MINIO_ACCESS_KEY=admin MINIO_SECRET_KEY=admin123 MINIO_IMAGE_BUCKET=incident-images
export BUSINESS_RISK_SSE_PERSISTENCE_BACKEND=memory
# 压测期间关闭准入限流，放行全量突发
export RATE_LIMIT_ENABLED=false
# 3000 并发同步落库：调大 HikariCP 池，避免默认 10 连接成为受理瓶颈
export SPRING_DATASOURCE_HIKARI_MAXIMUM_POOL_SIZE=200
export SPRING_DATASOURCE_HIKARI_MINIMUM_IDLE=20
nohup java -jar review-backend-0.0.1-SNAPSHOT.jar > /opt/review/backend/app.log 2>&1 &
echo BACKEND_STARTED
sleep 30
grep -aE 'Started ReviewBackendApplication|Rate limiter initialized|APPLICATION FAILED|Tomcat started on port' /opt/review/backend/app.log | tail -4
ss -tln | grep ':8080' >/dev/null && echo PORT_8080_UP || echo PORT_8080_DOWN