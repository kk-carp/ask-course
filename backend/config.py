"""集中读取环境配置（.env）；其它模块通过 settings 取值，不得直接 os.getenv。

P0 改动（相对 FDE 源）：
1. database_url 指向本项目库 arborseek_p0；
2. chat_base_url 默认指向公司既有 LLM 网关 openai.arborseek.com（OpenAI 兼容）；
3. session_cookie_name 改为本项目独立名，避免与官网/FDE 互相顶号；
4. 新增「课程空间 / 游客态 / 未命中转人工」三个 P0 配置块。
"""

from urllib.parse import urlparse

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SECRET_KEY = "change-me-for-local-dev"
DEFAULT_DEMO_PASSWORD = "demo1234"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # local=本机开发；prod=正式（禁默认密钥与演示密码）
    app_env: str = "local"

    database_url: str = (
        "postgresql+psycopg://postgres:postgres@localhost:5432/arborseek_p0"
    )

    # 公司既有 LLM 网关（OpenAI 兼容）：https://openai.arborseek.com/v1/chat/completions
    chat_base_url: str = "https://openai.arborseek.com/v1"
    chat_api_key: str = ""
    chat_model: str = "deepseek-chat"

    embed_model: str = "BAAI/bge-m3"
    embedding_dim: int = 1024
    embed_batch_size: int = 8

    retrieve_top_k: int = 5
    retrieve_min_score: float = 0.5
    # 混合检索 + 重排（默认双开；关 rerank 时仍用 retrieve_min_score 门控 dense 分）
    retrieve_use_hybrid: bool = True
    retrieve_use_rerank: bool = True
    retrieve_candidate_k: int = 20
    retrieve_rrf_k: int = 60
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    rerank_candidates: int = 20
    rerank_min_score: float = 0.5

    upload_dir: str = "data/uploads"
    max_upload_bytes: int = 50 * 1024 * 1024

    chunk_size: int = 800
    chunk_overlap: int = 100

    secret_key: str = DEFAULT_SECRET_KEY
    demo_password: str = DEFAULT_DEMO_PASSWORD
    session_cookie_name: str = "arborseek_agent_session"

    # 进程内限流：登录按用户名+IP，问答按登录用户（游客按匿名 id）
    login_rate_max: int = 20
    login_rate_window_seconds: int = 60
    ask_rate_max: int = 60
    ask_rate_window_seconds: int = 60

    # 会话保留天数；<=0 表示不自动清理
    data_retention_days: int = 90

    conversation_history_turns: int = 3
    conversation_compress_enabled: bool = True
    conversation_summary_max_chars: int = 2000

    # ------------------------------------------------------------------
    # P0 配置块一：课程知识空间
    # ------------------------------------------------------------------
    # 课程知识库所在的单一空间；课程详情页 9 板块文本化后统一入库到这里。
    course_space_id: str = "courses"
    course_space_name: str = "课程知识库"
    # off=不检查；warn=记录问题但允许入库；strict=四个最低板块不全则拒绝入库。
    # 默认严格校验；迁移历史语料时可显式改为 warn，试运行必须 strict。
    course_content_validation_mode: str = "strict"

    # ------------------------------------------------------------------
    # P0 配置块二：游客态（官网未登录访客）
    # ------------------------------------------------------------------
    # 游客会话 Cookie 名；与登录会话分离，避免互相顶号
    visitor_cookie_name: str = "arborseek_agent_visitor"
    visitor_cookie_max_age: int = 60 * 60 * 24 * 30
    # 游客问答限流（按匿名 id）
    guest_ask_rate_max: int = 40
    guest_ask_rate_window_seconds: int = 60

    # ------------------------------------------------------------------
    # P0 配置块三：未命中转人工（复用现有"弹售前二维码"承接点）
    # ------------------------------------------------------------------
    # 未命中时是否回传售前码；关闭时只回传 handoff_miss_answer
    handoff_enabled: bool = True
    # 兜底售前码（课程未匹配到任何映射时使用）；留空则返回 configured=false，不编造
    handoff_fallback_contact: str = ""
    handoff_fallback_name: str = ""
    # 未命中文案（与"系统故障"必须区分）
    handoff_miss_answer: str = (
        "这个问题我暂时没有可靠依据回答，已为你转接对应课程顾问。"
    )
    # 官网课程详情。未命中时按数字课程 ID 读取 pre_sale_service_qrcode；留空则不请求。
    course_detail_url: str = "https://arboradmin.saikr.com/miniapp/course/detail"
    course_detail_timeout_seconds: float = 3.0
    # 官网在售课程列表。游客未指定课程时用标题检索相关课；留空则不请求。
    course_list_url: str = "https://arboradmin.saikr.com/miniapp/course/list"
    course_list_timeout_seconds: float = 3.0
    # 运营审核清单。缺失时推荐与购买均关闭，不从官网标题猜测适配性。
    approved_course_catalog_path: str = "data/approved_courses.json"
    # 官网按课程详情页白名单灰度；默认关闭。
    pilot_course_ids: str = "42,43,99"
    pilot_percent: int = 0
    visitor_consultation_hours: int = 24

    @field_validator("app_env")
    @classmethod
    def _normalize_app_env(cls, value: str) -> str:
        normalized = (value or "").strip().lower()
        if normalized not in {"local", "prod"}:
            raise ValueError("APP_ENV 只能是 local 或 prod")
        return normalized

    @field_validator("course_content_validation_mode")
    @classmethod
    def _normalize_course_content_validation_mode(cls, value: str) -> str:
        normalized = (value or "warn").strip().lower()
        if normalized not in {"off", "warn", "strict"}:
            raise ValueError(
                "COURSE_CONTENT_VALIDATION_MODE 只能是 off、warn 或 strict"
            )
        return normalized


settings = Settings()


def is_local_env() -> bool:
    return settings.app_env == "local"


def is_prod_env() -> bool:
    return settings.app_env == "prod"


def session_https_only() -> bool:
    """正式环境要求 Cookie 只走 HTTPS；本机 http 开发保持可发送。"""
    return is_prod_env()


def assert_safe_for_environment() -> None:
    """正式环境拒绝开发配置，并强制满足 L0 的内容与人工兜底门禁。"""
    if not is_prod_env():
        return
    if not settings.secret_key or settings.secret_key == DEFAULT_SECRET_KEY:
        raise RuntimeError("正式环境禁止使用默认 SECRET_KEY，请改成随机字符串。")
    if not settings.demo_password or settings.demo_password == DEFAULT_DEMO_PASSWORD:
        raise RuntimeError("正式环境禁止使用默认 DEMO_PASSWORD。")
    if settings.course_content_validation_mode != "strict":
        raise RuntimeError("正式环境必须设置 COURSE_CONTENT_VALIDATION_MODE=strict。")
    if not 0 <= settings.pilot_percent <= 100:
        raise RuntimeError("PILOT_PERCENT 必须在 0 到 100 之间。")
    fallback = (settings.handoff_fallback_contact or "").strip()
    parsed = urlparse(fallback)
    if (
        not settings.handoff_enabled
        or parsed.scheme != "https"
        or not parsed.netloc
        or any(
            marker in fallback.casefold()
            for marker in ("placeholder", "replace-with", "example.")
        )
    ):
        raise RuntimeError("正式环境必须配置真实可访问的 HANDOFF_FALLBACK_CONTACT。")
