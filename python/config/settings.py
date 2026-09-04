"""
应用配置模块
============

作用：
    定义整个 Python 服务的所有配置项（数据库地址、API密钥、模型名称等）。
    相当于一个"全局设置中心"，程序启动时从这里读取所有需要的配置。

为什么用 Pydantic 的 BaseSettings 而不是普通字典？
    1. 类型安全：每个配置项都有明确的类型（str、int、bool 等），写错了会报错
    2. 自动读取环境变量：如果 .env 文件或系统环境变量中有同名变量，会自动覆盖默认值
    3. 数据验证：比如 persistence_backend 只能是 "sql" 或 "inmemory"，写别的值会直接报错
"""

# Literal 是 Python 类型提示工具，限制变量只能取指定的几个值。
# 比如 Literal["sql", "inmemory"] 意味着这个变量只能是 "sql" 或 "inmemory"，
# 如果你写 "redis"，IDE 和类型检查工具会警告你。
from typing import Literal

# BaseSettings 是 pydantic_settings 库提供的类，专门用来管理配置。
# 它继承自 Pydantic 的 BaseModel，额外增加了"从环境变量/文件读取配置"的能力。
from pydantic_settings import BaseSettings


# =============================================================================
# 应用配置类
# =============================================================================
# 这个类包含了整个 Python 服务的所有配置项。
# 每个类属性就是一个配置项，等号右边是默认值。
# 在实际部署时，这些值会被 .env 文件或环境变量覆盖。
class AppSettings(BaseSettings):
    # -------------------------------------------------------------------------
    # 基础应用配置
    # -------------------------------------------------------------------------
    # 运行环境：dev（开发）、test（测试）、prod（生产）
    # 不同环境可能有不同的行为，比如开发环境会打印更多调试信息
    app_env: str = "dev"
    # 服务监听的地址。"0.0.0.0" 表示监听所有网络接口（允许外部访问）
    # 如果写成 "127.0.0.1" 就只有本机能访问
    app_host: str = "0.0.0.0"
    # 服务监听的端口号。FastAPI 默认用 8000 端口
    app_port: int = 8000

    # -------------------------------------------------------------------------
    # 业务风险 Worker 配置（与 Java BFF 层通信相关）
    # -------------------------------------------------------------------------
    # Worker 心跳上报地址：Python 服务定期向 Java 后端发送"我还活着"的信号
    business_risk_worker_heartbeat_url: str = (
        "http://localhost:8080/api/internal/business-risk/worker-heartbeat"
    )
    # Worker 认证令牌：用于 Java 和 Python 之间的身份验证，防止非法请求
    business_risk_worker_token: str = "dev-callback"
    # 令牌放在 HTTP 请求的哪个 Header 中
    business_risk_worker_token_header: str = "X-Worker-Token"
    # Worker 版本号，用于 Java 端识别 Python 服务版本
    business_risk_worker_version: str = "2026.05.30"
    # 最大并发数：同时处理几个业务风险评估任务
    business_risk_worker_max_concurrency: int = 4
    # 心跳间隔：每隔多少秒向 Java 后端报告一次"我还活着"
    business_risk_worker_heartbeat_interval_seconds: int = 15
    # 支持的业务风险 Schema 版本列表（逗号分隔）
    business_risk_schema_versions_supported: str = "2.0,3.0"
    # Java 端预处理支持的版本
    business_risk_java_preprocess_versions_supported: str = "3.0"

    # -------------------------------------------------------------------------
    # Kafka 异步链路配置（Java 生产者 → Python 消费者 → 回调回 Java）
    # -------------------------------------------------------------------------
    # 总开关：false 时不启动消费者/生产者（回滚开关，配合 auto_offset_reset 排干积压）
    kafka_enabled: bool = False
    # Kafka broker 地址列表（逗号分隔）
    kafka_bootstrap_servers: str = "localhost:9092"
    # 消费者组 ID（独立组，Java 不再消费同一 topic）
    kafka_group_id: str = "python-review-worker"
    # Topic 1：Java 下发审查任务（Java 生产，Python 消费）
    kafka_review_tasks_topic: str = "ai.review.tasks"
    # Topic 2：Python 回调通知（Python 生产，Java 消费）
    kafka_review_callbacks_topic: str = "ai.review.callbacks"
    # 并发上限：同时运行多少个审查流水线（对齐 LLM 配额，别把配额打爆）
    kafka_max_concurrency: int = 4
    # 单次 poll 最多拉取的消息数
    kafka_max_poll_records: int = 20
    # 两次 poll 之间的最大间隔（ms）：单任务 LLM 可能跑 180s，批处理需留足余量防 rebalance
    kafka_max_poll_interval_ms: int = 1800000
    # 瞬时失败（LLM 超时/网络）进程内重试次数
    kafka_transient_retries: int = 3
    # 瞬时失败重试退避间隔（ms）
    kafka_transient_backoff_ms: int = 2000
    # Redis SETNX 去重开关：重复消息不重复处理，避免烧 LLM token
    kafka_dedup_enabled: bool = True
    # 去重键 TTL（秒）：大于单任务最长生命周期即可
    kafka_dedup_ttl_seconds: int = 86400
    # SASL 鉴权占位（内网可 PLAINTEXT，留出鉴权位）
    kafka_security_protocol: str = "PLAINTEXT"
    kafka_sasl_mechanism: str = ""
    kafka_sasl_username: str = ""
    kafka_sasl_password: str = ""

    # -------------------------------------------------------------------------
    # 数据库连接配置
    # -------------------------------------------------------------------------
    # MySQL 数据库连接字符串，格式：mysql://用户名:密码@主机:端口/数据库名
    mysql_url: str = "mysql://user:pass@localhost:3306/review"
    # Redis 连接字符串，用于缓存和分布式锁
    redis_url: str = "redis://localhost:6379/0"

    # -------------------------------------------------------------------------
    # 持久化后端选择
    # -------------------------------------------------------------------------
    # 任务数据的存储方式：
    #   "sql"      → 存到 MySQL 数据库（生产环境用）
    #   "inmemory" → 存在内存里（开发/测试用，重启后数据丢失）
    persistence_backend: Literal["sql", "inmemory"] = "inmemory"

    # -------------------------------------------------------------------------
    # MinIO 对象存储配置
    # -------------------------------------------------------------------------
    # MinIO 是一个开源的对象存储服务（类似 AWS S3），用来存储文件。
    # 在本项目中用来存储审查报告和图片。
    minio_endpoint: str = "http://localhost:9000"
    # 访问 MinIO 的认证信息
    minio_access_key: str = "admin"
    minio_secret_key: str = "admin123"
    # 存储审查报告的"桶"（Bucket，类似文件夹的概念）
    minio_bucket: str = "review-reports"
    # 存储事故文档相关图片的桶
    minio_image_bucket: str = "incident-images"

    # -------------------------------------------------------------------------
    # OCR 与文档路径
    # -------------------------------------------------------------------------
    # Tesseract OCR 引擎的数据文件路径（用于图片文字识别）
    tesseract_data_path: str = ""
    # 事故文档（Incident Docs）存放目录
    incident_docs_dir: str = "D:/IncidentDocs"

    # -------------------------------------------------------------------------
    # ChromaDB 向量数据库配置
    # -------------------------------------------------------------------------
    # ChromaDB 是一个向量数据库，用来存储文档的"向量表示"（Embedding）。
    # 什么是向量？简单说就是把文字变成一组数字，方便计算"语义相似度"。
    # 比如"汽车"和"轿车"的向量会很接近，而"汽车"和"香蕉"的向量就相差很远。
    chroma_path: str = "D:/Chroma"
    # ChromaDB 中"集合"的名称，类似数据库中的"表"
    chroma_collection: str = "incident_vectors"
    # BM25 关键词索引文件的存储路径（BM25 是一种经典的文本检索算法）
    chroma_keyword_index_path: str = "D:/Chroma/incident_keywords.jsonl"

    # -------------------------------------------------------------------------
    # Elasticsearch 配置
    # -------------------------------------------------------------------------
    # Elasticsearch 是一个全文搜索引擎，这里用来做关键词检索。
    # 和 ChromaDB（向量检索）配合使用，实现"混合检索"——
    # 既按语义相似度找，也按关键词匹配找，最后合并结果。
    elasticsearch_url: str = "http://localhost:9200"
    # ES 中的索引名称（类似数据库中的"表"）
    es_index_name: str = "incident_keywords"

    # -------------------------------------------------------------------------
    # LLM 大语言模型配置
    # -------------------------------------------------------------------------
    # LLM API 地址。这里用的是阿里云 DashScope 的 OpenAI 兼容接口。
    # "兼容接口"意味着虽然用的是通义千问模型，但调用方式和 OpenAI 一样，
    # 所以可以复用 OpenAI 的客户端代码。
    llm_api_base: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    # API 密钥，用于身份认证。生产环境中应该从环境变量读取，不能硬编码
    llm_api_key: str = ""
    # 使用的大语言模型名称。qwen-plus 是通义千问的增强版
    llm_model: str = "qwen-plus"
    # 嵌入模型名称。嵌入模型负责把文本转成向量，用于语义搜索
    embedding_model: str = "microsoft/codebert-base"

    # -------------------------------------------------------------------------
    # RAG 检索参数
    # -------------------------------------------------------------------------
    # Top-K：检索时返回最相关的前 K 条结果。
    # 比如 top_k=5 就是返回最相关的 5 条文档片段。
    top_k: int = 5

    # RRF（Reciprocal Rank Fusion，倒数排名融合）的参数。
    # 当同时使用向量检索和关键词检索时，需要用 RRF 算法合并两路结果。
    # rrf_k 是 RRF 公式中的平滑常数，防止排名靠前的结果权重过大。
    rrf_k: int = 60
    # RAG 检索结果最多包含多少个 Token（词元）。
    # Token 是 LLM 处理文本的基本单位，大约 1 个中文字 ≈ 1-2 个 Token。
    # 限制 Token 数是为了不超出 LLM 的上下文窗口。
    rag_max_tokens: int = 2000

    # -------------------------------------------------------------------------
    # BFF（Backend For Frontend）AST 解析配置
    # -------------------------------------------------------------------------
    # BFF 是 Java 后端服务的地址。Python 需要调用 Java 端来解析代码的 AST
    # （抽象语法树，即把源代码解析成结构化的树形表示）。
    bff_base_url: str = "http://localhost:8080"
    bff_api_key: str = ""
    # 请求 AST 分块的超时时间（秒）
    bff_chunk_timeout: int = 30
    # 每个代码块的最大字符数
    bff_chunk_max_chars: int = 1500
    # 代码块之间的重叠字符数。重叠是为了保证上下文不丢失，
    # 比如第 1 块是 1-1500 行，第 2 块从 1200 行开始（重叠 300 字符）
    bff_chunk_overlap: int = 300

    # -------------------------------------------------------------------------
    # Cross-Encoder 精排配置
    # -------------------------------------------------------------------------
    # 检索分两阶段：
    #   1. 粗排（Retrieval）：用向量检索/BM25 快速找出候选文档（快但不够准）
    #   2. 精排（Rerank）：用 Cross-Encoder 模型对候选文档重新打分（慢但更准）
    # 这就像一个选秀节目：海选（粗排）选出 100 人，决赛（精排）再精选出 5 人。
    enable_rerank: bool = True
    # 精排使用的模型。cross-encoder/ms-marco-MiniLM-L-6-v2 是一个轻量级
    # 但效果不错的重排序模型
    rerank_model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    # -------------------------------------------------------------------------
    # 查询改写配置
    # -------------------------------------------------------------------------
    # 查询改写：在检索前先用 LLM 把用户的原始查询"翻译"成更好的检索词。
    # 比如用户问"这段代码有没有 SQL 注入风险？"，改写后可能变成"SQL 注入 参数化查询"
    enable_query_rewrite: bool = False

    # -------------------------------------------------------------------------
    # 检索分数阈值
    # -------------------------------------------------------------------------
    # 最低检索分数。低于这个分数的检索结果会被丢弃，避免把不相关的内容喂给 LLM。
    # 分数范围通常是 0~1，0.15 表示至少要有 15% 的相关度。
    min_retrieval_score: float = 0.15

    # -------------------------------------------------------------------------
    # 遥测（Telemetry）配置
    # -------------------------------------------------------------------------
    # 遥测就是收集系统运行的指标数据（耗时、成功率等）。
    # "logging" → 把遥测数据写到日志里
    # "noop"    → 不收集（noop = no operation，空操作）
    telemetry_backend: Literal["logging", "noop"] = "logging"

    # -------------------------------------------------------------------------
    # 语义热点扫描配置
    # -------------------------------------------------------------------------
    # 语义热点扫描：自动扫描代码变更，找出可能存在风险的"热点"区域。
    # 比如某个文件最近频繁出 bug，就会被标记为"热点"。
    # 是否启用语义热点扫描
    semantic_hotspot_enabled: bool = True
    # 并发数：同时分析几个文件
    semantic_hotspot_concurrency: int = 5
    # 置信度阈值：只有模型认为风险概率超过这个值的结果才会被保留
    semantic_hotspot_confidence_threshold: float = 0.6

    # -------------------------------------------------------------------------
    # Pydantic 模型配置
    # -------------------------------------------------------------------------
    # 告诉 Pydantic 从 .env 文件中读取配置。
    # .env 文件是一个纯文本文件，每行一个 "键=值"，专门用来存放环境变量。
    # 这样敏感信息（如 API 密钥）就不会出现在代码中。
    model_config = {
        "env_file": ".env",          # 指定 .env 文件的路径
        "env_file_encoding": "utf-8",  # 文件编码
    }
