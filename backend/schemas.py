"""对外 API 的 Pydantic 模型；路由只做校验与响应转换，字段与实现保持一致。"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    question: str = Field(min_length=1)
    conversation_id: UUID | None = None
    request_id: UUID | None = None
    # --- P0 新增：转人工路由与归因所需的最小上下文 ---
    # 当前所在课程（前端从 /course/:courseId 解析得到）；用于一级路由精确匹配售前
    course_id: str | None = None
    # 来源渠道：site_widget | course_page | internal_tool
    channel: str | None = None


class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class MeResponse(BaseModel):
    id: str
    username: str
    role: str
    allowed_spaces: list[str]
    can_manage_documents: bool = False


class SourceItem(BaseModel):
    document_id: UUID
    title: str
    space_id: str
    path: str | None = None
    score: float | None = None
    snippet: str | None = None


class OwnerInfo(BaseModel):
    """课程对应的售前联系人；configured=false 表示未配置，不编造联系方式。"""

    configured: bool
    topic_key: str | None = None
    topic_name: str | None = None
    name: str | None = None
    contact: str | None = None


class RelatedCourse(BaseModel):
    """官网课程列表中的一门课。卡片字段来自列表/审核，不含课程正文。"""

    id: str
    title: str
    description: str | None = None
    purchase_url: str | None = None
    source_url: str | None = None
    cover_url: str | None = None
    reason: str | None = None
    requirements: list[str] = Field(default_factory=list)
    pending: list[str] = Field(default_factory=list)


class AskResponse(BaseModel):
    answer: str
    hit: bool | None = None
    sources: list[SourceItem] = Field(default_factory=list)
    conversation_id: UUID | None = None
    owner: OwnerInfo | None = None
    related_courses: list[RelatedCourse] = Field(default_factory=list)
    intent: str | None = None
    error_type: str | None = None
    llm_called: bool = False
    generation_called: bool = False
    prompt_tokens: int = 0
    completion_tokens: int = 0
    fact_sources: list[dict[str, str]] = Field(default_factory=list)
    handoff_summary: str | None = None
    fallback_contact: str | None = None


class ConversationItem(BaseModel):
    id: UUID
    created_at: datetime
    updated_at: datetime
    message_count: int
    preview: str


class MessageItem(BaseModel):
    id: UUID
    role: str
    content: str
    created_at: datetime


class TopicOwnerUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    topic_key: str = Field(min_length=1, max_length=64)
    topic_name: str = Field(min_length=1, max_length=128)
    keywords: str = ""
    name: str = Field(min_length=1, max_length=64)
    contact: str = Field(min_length=1, max_length=255)


class TopicOwnerResponse(BaseModel):
    topic_key: str
    topic_name: str
    keywords: str
    name: str
    contact: str


class DocumentResponse(BaseModel):
    id: UUID
    title: str
    space_id: str
    course_id: str | None = None
    status: str
    chunk_count: int
    error: str | None = None
    path: str | None = None


class DocumentIdListRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ids: list[str] = Field(min_length=1, max_length=100)


class DocumentBatchResult(BaseModel):
    done: int
    skipped: int


class HealthResponse(BaseModel):
    api: bool
    database: bool
    embedding_loaded: bool


class MetricsResponse(BaseModel):
    """当前进程启动后累计；重启清零。不含问题正文。"""

    ask_total: int
    ask_hit: int
    ask_miss: int
    ask_error_502: int
    ask_error_503: int
    ask_429: int
    llm_calls: int
    prompt_tokens_total: int
    completion_tokens_total: int
    funnel_events_30d: dict[str, int] = Field(default_factory=dict)
    latency_ms: dict[str, dict[str, float]] = Field(default_factory=dict)
