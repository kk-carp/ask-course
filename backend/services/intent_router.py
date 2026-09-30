"""售前意图规则路由：先判断再执行，不让模型选择工具。"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import StrEnum

from backend.schemas import RelatedCourse
from backend.services.approved_courses import (
    get_approved_course,
    load_approved_courses,
    load_recommendable_courses,
)
from backend.services.course_catalog_service import (
    search_related_courses,
)
from backend.services.handoff_service import resolve_handoff
from backend.services.qa_service import AskResult

_log = logging.getLogger("backend.intent_router")

ANSWER_ASK_BASIS = (
    "可以。先告诉我你的基础（例如是否学过编程 / ROS）和学习目标"
    "（就业、竞赛、了解机器狗等），我再按官网在售课帮你缩小范围。"
)
ANSWER_ASK_WHICH_COURSE = "可以。请先告诉我要购买的课程名称，或从左侧选中一门课后再说付款。"
ANSWER_HANDOFF = "这个问题需要课程顾问确认。请使用下方联系方式继续咨询。"
ANSWER_HANDOFF_UNAVAILABLE = "这个问题需要课程顾问确认，但当前没有可用的联系方式。请稍后重试。"
ANSWER_COURSE_UNAVAILABLE = "暂未核实这门课的在售状态和购买入口，请先不要付款，可联系课程顾问确认。"
ANSWER_PAY = (
    "确认购买「{title}」后，请使用下方按钮打开官网课程详情页完成付款。"
    "页面上的购买按钮为官方收款入口。讲价、退款、发票请联系课程顾问。"
)
ANSWER_RECOMMEND_LIST = (
    "根据你的问题，官网在售课里较相关的有：\n{lines}\n"
    "需要了解某一门的内容或付款，直接说课程名或选中该课再问。"
    "若要覆盖更多方向，也可以再说具体任务（如巡检、机械臂、大模型）。"
)


class Intent(StrEnum):
    commercial = "commercial"
    advisor = "advisor"
    pay = "pay"
    recommend = "recommend"
    content = "content"


@dataclass(frozen=True)
class RoutedTurn:
    """handled=True 表示本轮已给出固定回复，调用方不得再跑 RAG。"""

    handled: bool
    intent: Intent
    result: AskResult
    related_courses: tuple[RelatedCourse, ...] = ()
    course_id: str | None = None


_COMMERCIAL = re.compile(
    r"讲价|便宜|砍价|少收|减免|退款|退费|发票|对公|开票|合同价"
)
_ADVISOR = re.compile(
    r"找顾问|课程顾问|找人工|转人工|人工客服|企微顾问|联系顾问|我想找课程顾问"
)
_PAY = re.compile(r"付款|支付|购买|下单|怎么买|报名缴费|缴费|收银台|去买")
_RECOMMEND = re.compile(
    r"推荐一门适合我的课程|按我的基础帮我选课|推荐|帮我选|"
    r"哪门课|有哪些课|哪些课|有没有.+课|还有.+课|其他.+课|"
    r"所有.+课|相关课程|想看.+课|看看有哪些|适合我吗|适不适合我"
)
_EMPLOYMENT_GOAL = re.compile(r"(?:想|希望|准备|为了|打算).{0,6}(?:就业|找工作|求职|转行)")
_ROS_BACKGROUND = re.compile(r"学过\s*ros", re.IGNORECASE)
_UNDIRECTED_RECOMMEND = frozenset(
    {
        "推荐一门适合我的课程",
        "按我的基础帮我选课",
        "帮我推荐课",
        "推荐一门课",
        "帮我选课",
    }
)


def classify_intent(question: str) -> Intent:
    """优先级：讲价退款发票 → 找顾问 → 付款 → 推荐 → 内容。"""
    text = (question or "").strip()
    if not text:
        return Intent.content
    if _COMMERCIAL.search(text):
        return Intent.commercial
    if _ADVISOR.search(text):
        return Intent.advisor
    if _PAY.search(text):
        return Intent.pay
    if text in _UNDIRECTED_RECOMMEND or _RECOMMEND.search(text) or _EMPLOYMENT_GOAL.search(text):
        return Intent.recommend
    return Intent.content


def _empty_result(answer: str, *, owner=None) -> AskResult:
    return AskResult(
        answer=answer,
        hit=False,
        sources=[],
        owner=owner,
        llm_called=False,
    )


def _handoff_result(
    question: str,
    *,
    course_id: str | None,
    answer: str,
) -> AskResult:
    handoff = resolve_handoff(question=question, course_id=course_id)
    return _empty_result(answer if handoff.owner.configured else ANSWER_HANDOFF_UNAVAILABLE, owner=handoff.owner)


def recommend_has_direction(question: str) -> bool:
    """已知无方向开场句不调列表；其余推荐句才用列表能否命中判断方向。"""
    text = (question or "").strip()
    if text in _UNDIRECTED_RECOMMEND:
        return False
    return True


def recommend_catalog_hits(question: str) -> bool:
    """可推荐目录是否对当前问句有命中。"""
    search_query = question or ""
    if re.search(r"具身", search_query):
        search_query = f"{search_query} 机器人 四足 机械臂 巡检 机器狗"
    return bool(
        search_related_courses(search_query, courses=load_recommendable_courses())
    )


def should_enter_guest_consultation(
    intent: Intent,
    question: str,
    *,
    pending_field: str | None,
    looks_like_profile_reply: bool = False,
) -> bool:
    """游客问诊门闸：商业/顾问/付款永不进；无方向或未命中才问诊。

    优先级见 ask_orchestrator 模块说明。有方向且目录命中时直接列课，不进问诊。
    就业类走多轮问诊。问诊进行中仅画像短答/推荐意图继续问诊；课程事实问题放行。
    """
    if intent in {Intent.commercial, Intent.advisor, Intent.pay}:
        return False
    if pending_field:
        if intent is Intent.recommend:
            return True
        return bool(intent is Intent.content and looks_like_profile_reply)
    if intent is Intent.recommend:
        if not recommend_has_direction(question):
            return True
        if _EMPLOYMENT_GOAL.search(question or ""):
            return True
        return not recommend_catalog_hits(question)
    if intent is Intent.content and looks_like_profile_reply:
        return True
    return False


def handle_routed_turn(
    question: str,
    *,
    course_id: str | None = None,
    intent_override: str | None = None,
) -> RoutedTurn:
    """按意图给出固定回复或声明交给 RAG（handled=False）。"""
    intent = classify_intent(question)
    if intent is Intent.content and intent_override in {item.value for item in Intent}:
        intent = Intent(intent_override)
    explicit = (course_id or "").strip() or None
    _log.info("intent=%s course_id=%s", intent.value, explicit or "")

    if intent is Intent.content:
        return RoutedTurn(
            handled=False,
            intent=intent,
            result=_empty_result(""),
            course_id=explicit,
        )

    if intent in {Intent.commercial, Intent.advisor}:
        result = _handoff_result(
            question,
            course_id=explicit,
            answer=ANSWER_HANDOFF,
        )
        return RoutedTurn(
            handled=True,
            intent=intent,
            result=result,
            course_id=explicit,
        )

    if intent is Intent.pay:
        pay_course_id = explicit
        related: tuple[RelatedCourse, ...] = ()
        if pay_course_id is None:
            # 问题里带了课名才搜列表；纯「怎么付款」只反问。
            if len((question or "").strip()) > 4:
                approved = {item.id for item in load_approved_courses()}
                matches = [item for item in search_related_courses(question) if item.course_id in approved]
                if matches:
                    pay_course_id = matches[0].course_id
        if pay_course_id is None:
            return RoutedTurn(
                handled=True,
                intent=intent,
                result=_empty_result(ANSWER_ASK_WHICH_COURSE),
                course_id=None,
            )
        approved_course = get_approved_course(pay_course_id)
        if approved_course is None:
            return RoutedTurn(
                handled=True,
                intent=intent,
                result=_empty_result(ANSWER_COURSE_UNAVAILABLE),
                course_id=pay_course_id,
            )
        related = (RelatedCourse(id=approved_course.id, title=approved_course.title, description=None, purchase_url=approved_course.purchase_url),)
        answer = ANSWER_PAY.format(title=approved_course.title)
        return RoutedTurn(
            handled=True,
            intent=intent,
            result=_empty_result(answer),
            related_courses=related,
            course_id=pay_course_id,
        )

    # recommend
    if _EMPLOYMENT_GOAL.search(question):
        known = "你提到学过 ROS，" if _ROS_BACKGROUND.search(question) else ""
        answer = (
            f"{known}目标是就业。为了筛选合适课程，还需要确认你想从事的机器人方向、"
            "目前的项目实践、是否有练习硬件，以及每周可投入时间。"
        )
        return RoutedTurn(
            handled=True,
            intent=intent,
            result=_empty_result(answer),
            course_id=explicit,
        )
    if not recommend_has_direction(question):
        return RoutedTurn(
            handled=True,
            intent=intent,
            result=_empty_result(ANSWER_ASK_BASIS),
            course_id=explicit,
        )

    recommendable = load_recommendable_courses()
    search_query = question
    if re.search(r"具身", question or ""):
        # 标题里少见「具身」：用常见具身方向词扩召回，仍限制在可推荐池。
        search_query = f"{question} 机器人 四足 机械臂 巡检 机器狗"
    matches = search_related_courses(search_query, courses=recommendable)
    if not matches:
        return RoutedTurn(
            handled=True,
            intent=intent,
            result=_empty_result(ANSWER_ASK_BASIS),
            course_id=explicit,
        )

    approved = {item.id: item for item in load_approved_courses()}
    related = tuple(
        RelatedCourse(
            id=item.course_id,
            title=item.title,
            description=item.description or None,
            purchase_url=approved[item.course_id].purchase_url
            if item.course_id in approved else None,
        )
        for item in matches
    )
    lines = "\n".join(f"- {item.title}（{item.id}）" for item in related)
    return RoutedTurn(
        handled=True,
        intent=intent,
        result=_empty_result(ANSWER_RECOMMEND_LIST.format(lines=lines)),
        related_courses=related,
        course_id=explicit,
    )
