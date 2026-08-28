from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


# backend目录路径，用来定位.env。Path写法可以同时兼容Windows和Linux。
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """应用运行配置。

    密钥和连接字符串放在backend/.env中；代码只声明字段、默认值和读取方式。
    默认使用内存存储，因此没有安装Redis和PostgreSQL时也可以运行自测。
    """

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "smart-customer-service-api"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_reload: bool = True
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    doubao_api_key: str = "YOUR_DOUBAO_API_KEY"
    doubao_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    doubao_model: str = "doubao-seed-1-6-250615"
    doubao_temperature: float = 0.3
    # 最终回答也属于外部网络调用，必须设置超时，避免接口异常时请求一直占用服务资源。
    doubao_timeout_seconds: float = 15.0
    # LangChain会在网络抖动时自动重试。限制为1次可以兼顾成功率和用户等待时间。
    doubao_max_retries: int = 1

    # 知识标准问法默认复用回答模型，也可以通过环境变量单独指定更擅长改写的模型。
    knowledge_question_model: str = ""
    knowledge_question_temperature: float = 0.6
    knowledge_question_timeout_seconds: float = 30.0

    # 用户语义理解配置。hybrid表示LLM优先、关键词兜底，是当前推荐模式。
    understanding_mode: Literal["keyword", "llm", "hybrid"] = "hybrid"
    # 理解模型使用独立供应商配置，避免和最终回答模型共用Key、地址及模型名称。
    understanding_api_key: str = "YOUR_UNDERSTANDING_API_KEY"
    understanding_base_url: str = "https://api.deepseek.com"
    understanding_model: str = "deepseek-v4-flash"
    understanding_temperature: float = 0.0
    # 理解阶段位于用户请求主链路，超时后hybrid模式会快速回退关键词识别。
    understanding_timeout_seconds: float = 10.0
    understanding_confidence_threshold: float = 0.65

    # Redis只保存短期编排状态。安装服务后把SESSION_STORE_BACKEND改成redis即可。
    session_store_backend: Literal["memory", "redis"] = "memory"
    redis_url: str = "redis://127.0.0.1:6379/0"
    redis_session_ttl_seconds: int = 1800
    redis_session_key_prefix: str = "cs:session:"

    # Redis Search语义检索配置。知识库和LangCache使用不同索引，避免两类数据互相污染。
    semantic_search_enabled: bool = False
    embedding_api_key: str = "YOUR_EMBEDDING_API_KEY"
    embedding_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    embedding_model: str = "doubao-embedding-vision-251215"
    embedding_dimension: int = 2048
    embedding_timeout_seconds: float = 15.0
    knowledge_index_name: str = "idx:cs:knowledge"
    knowledge_key_prefix: str = "cs:knowledge:doc:"
    knowledge_question_map_key_prefix: str = "cs:knowledge:question-map:"
    knowledge_distance_threshold: float = 0.38
    knowledge_top_k: int = 3
    langcache_index_name: str = "idx:cs:langcache"
    langcache_key_prefix: str = "cs:langcache:entry:"
    langcache_distance_threshold: float = 0.20
    langcache_ttl_seconds: int = 3600
    langcache_frequency_threshold: int = 5
    langcache_gap_index_name: str = "idx:cs:langcache-gap"
    langcache_gap_key_prefix: str = "cs:langcache:gap:"
    langcache_gap_window_seconds: int = 86400
    # 只允许低风险静态意图进入语义缓存，订单、积分等动态业务仍然调用Tool。
    # order_query同时包含实时订单Tool和静态订单说明，组合问题需要允许检索订单知识。
    semantic_cache_intents: str = (
        "knowledge_query,activity_rules,benefits_query,points_rules,refund_request,order_query"
    )

    # PostgreSQL保存长期聊天记录。连接使用SQLAlchemy异步引擎和asyncpg驱动。
    persistence_backend: Literal["memory", "postgres"] = "memory"
    database_url: str = "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/smart_customer_service"
    database_echo: bool = False
    database_auto_create_tables: bool = False

    # 问题学习只收集明确负面信号；原始信号先可靠落库，Embedding和聚类由后台任务异步完成。
    learning_enabled: bool = False
    # Python进程每天按指定时区执行；多实例通过PostgreSQL advisory lock互斥。
    learning_scheduler_enabled: bool = False
    learning_schedule_timezone: str = "Asia/Shanghai"
    learning_schedule_hour: int = 3
    learning_schedule_minute: int = 0
    learning_max_batches: int = 100
    learning_batch_size: int = 100
    learning_embedding_concurrency: int = 5
    learning_max_retries: int = 3
    learning_stale_after_minutes: int = 30
    # 这是问题聚类距离，不影响线上知识召回阈值；后续应使用人工审核样本单独评测。
    learning_cluster_distance_threshold: float = 0.38
    # 普通问题达到任一门槛后进入人工审核；投诉属于高风险信号，单条即可进入审核。
    learning_review_occurrence_threshold: int = 3
    learning_review_user_threshold: int = 2
    # 问题标准回答复用豆包回答模型，但使用独立温度和超时，避免影响聊天参数。
    learning_answer_temperature: float = 0.2
    learning_answer_timeout_seconds: float = 30.0
    # 审核通过后生成知识草稿标题、标准问法和回归测试问法。
    learning_package_temperature: float = 0.5
    learning_package_timeout_seconds: float = 30.0
    # 知识发布门禁使用真实Redis Search竞争环境进行自动召回验收。
    release_evaluation_top_k: int = 5
    release_min_recall_at_1: float = 0.8
    release_min_recall_at_3: float = 1.0
    release_min_threshold_recall: float = 0.8
    # 困难负样本不应该召回当前候选知识；默认不允许任何阈值内误命中。
    release_max_hard_negative_false_positive_rate: float = 0.0
    release_evaluation_concurrency: int = 3

    # Java 业务 Tool 服务配置。Python 只负责编排，不直接读取 Java 拥有的业务表。
    business_tool_base_url: str = "http://127.0.0.1:8081"
    # Python 与 Java 必须配置相同令牌；真实令牌只写入 .env 或部署平台的环境变量。
    business_tool_internal_token: str = ""
    # Tool 调用处于用户请求主链路，必须限制等待时间，避免 Java 故障拖垮 Python 服务。
    business_tool_timeout_seconds: float = 5.0

    # Nacos 3.x承担控制面和服务发现：管理提示词并发现Java MCP Server。
    # 默认关闭，单元测试和纯本地模式不会访问外部Nacos；生产环境通过.env开启。
    nacos_enabled: bool = False
    nacos_server_addr: str = "http://127.0.0.1:8848"
    nacos_namespace: str = "public"
    nacos_username: str = ""
    nacos_password: str = ""
    nacos_prompt_label: str = "stable"
    nacos_timeout_seconds: float = 5.0

    # Python是MCP Host/Client，Java是MCP Server。Nacos发现失败时使用本地URL降级。
    mcp_enabled: bool = False
    mcp_server_name: str = "smart-customer-business-tools"
    mcp_server_url: str = "http://127.0.0.1:8081/mcp"

    # Tool 数量增加后，先用 Redis Search 从动态 MCP 目录召回少量候选，再交给 LLM 最终决策。
    # 召回层不执行 Tool；任何超时、低相似度或索引异常都会自动回退到完整工具目录。
    tool_retrieval_enabled: bool = False
    tool_retrieval_index_name: str = "idx:cs:mcp-tools"
    tool_retrieval_key_prefix: str = "cs:mcp:tool:"
    tool_retrieval_top_k: int = 3
    tool_retrieval_max_distance: float = 0.80
    tool_retrieval_timeout_seconds: float = 2.0

    # 认证模块完成前使用固定测试用户，正式环境必须替换为登录态中的user_id。
    demo_user_id: str = "demo-user-001"

    @property
    def cors_origin_list(self) -> list[str]:
        """把逗号分隔的CORS配置转成FastAPI需要的列表。"""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def has_real_api_key(self) -> bool:
        """判断是否配置了真实模型Key。"""
        key = self.doubao_api_key.strip()
        return bool(key) and not key.startswith("YOUR_")

    @property
    def has_real_understanding_api_key(self) -> bool:
        """判断语义理解是否配置了独立的真实API Key。"""
        key = self.understanding_api_key.strip()
        return bool(key) and not key.startswith("YOUR_")

    @property
    def has_real_embedding_api_key(self) -> bool:
        """判断是否配置了可用于Redis向量检索的真实Embedding Key。"""
        key = self.embedding_api_key.strip()
        return bool(key) and not key.startswith("YOUR_")

    @property
    def semantic_cache_intent_set(self) -> set[str]:
        """把逗号分隔的静态知识意图转换为便于路由判断的集合。"""
        return {
            intent.strip()
            for intent in self.semantic_cache_intents.split(",")
            if intent.strip()
        }

    @property
    def effective_understanding_model(self) -> str:
        """返回语义理解使用的模型；没有单独配置时复用回答模型。

        这样开发阶段只需要配置一个模型，未来也可以换成更便宜、更快的分类模型。
        """
        return self.understanding_model.strip() or self.doubao_model

    @property
    def effective_knowledge_question_model(self) -> str:
        """返回标准问法生成模型；未单独配置时复用回答模型。"""
        return self.knowledge_question_model.strip() or self.doubao_model


@lru_cache
def get_settings() -> Settings:
    """缓存配置对象，避免每次请求都重新读取.env。"""
    return Settings()
