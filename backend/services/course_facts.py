"""统一读取课程文字资料和官网实时商业字段；缺项、冲突不交给模型猜测。"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

import httpx

from backend.config import settings

ROOT = Path(__file__).resolve().parents[2]
_cache: dict[str, tuple[float, dict, str]] = {}
_TOPICS = (
    ("promotion", r"优惠|折扣|活动|促销"),
    ("price", r"价格|多少钱|售价|费用|学费"),
    ("validity", r"有效期|看多久|观看期限|永久|长期有效"),
    ("hardware", r"硬件|设备|自备|真机|没.*机械臂.*能学"),
    ("basis", r"什么基础|基础要求|零基础|入门门槛|前置|先修"),
    ("audience", r"适合谁|适用人群|适合人群|面向谁"),
    ("certificate", r"证书|结业"),
    ("schedule", r"开课|开始时间|什么时候|学习安排|授课|上课|直播|录播|学习方式|线上"),
    ("outline", r"目录|大纲|学什么|学哪些|课程内容|具体.*内容|讲什么|课程介绍"),
)


def fact_topic(question: str) -> str | None:
    return next((topic for topic, pattern in _TOPICS if re.search(pattern, question)), None)


def live_course(course_id: str, *, force_refresh: bool = False) -> tuple[dict, str] | None:
    """最多缓存一分钟；请求失败不以过期价格作答。"""
    if not course_id.isdigit() or not settings.course_detail_url:
        return None
    cached = _cache.get(course_id)
    if not force_refresh and cached and cached[0] > time.monotonic():
        return cached[1], cached[2]
    try:
        with httpx.Client(timeout=settings.course_detail_timeout_seconds, follow_redirects=False) as client:
            response = client.get(f"{settings.course_detail_url.rstrip('/')}/{course_id}")
        response.raise_for_status()
        course = response.json()["data"]["course"]
        if str(course.get("id")) != course_id:
            return None
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return None
    collected_at = datetime.now(timezone.utc).isoformat()
    _cache[course_id] = (time.monotonic() + 60, course, collected_at)
    return course, collected_at


def _money(value: object) -> str | None:
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0:
            return None
        formatted = format(amount, "f")
        return formatted.rstrip("0").rstrip(".") if "." in formatted else formatted
    except InvalidOperation:
        return None


def answer_course_fact(question: str, course_id: str) -> tuple[str, list[dict]] | None:
    """返回答案及可追溯来源。None 表示此问题应继续走正文检索。"""
    topic = fact_topic(question)
    if not topic:
        return None
    if topic in {"price", "promotion"}:
        live = live_course(course_id)
        if live is None:
            return "暂时无法读取官网最新价格和活动，请查看课程详情页或向课程顾问确认。", []
        course, timestamp = live
        price = _money(course.get("price"))
        original = _money(course.get("original_price"))
        answer = f"官网当前标价为 {price} 元，最终金额以官网下单页面为准。" if price else "官网暂未提供可核实的价格，需要课程顾问确认。"
        if topic == "promotion":
            if price and original and Decimal(original) > Decimal(price):
                answer += f"官网同时列出原价 {original} 元。"
            if course.get("group_buy_activity") or course.get("flash_sale"):
                answer += "官网显示活动信息，参与条件和截止时间请查看官网活动说明。"
            else:
                answer += "当前接口未提供额外团购或秒杀活动信息；个别让价需要课程顾问确认。"
        return answer, [{"source": f"{settings.course_detail_url.rstrip('/')}/{course_id}", "updated_at": timestamp, "status": "official"}]
    try:
        registry = json.loads((ROOT / "data/course_facts.json").read_text(encoding="utf-8"))
        record = registry[course_id]
        fact = record["facts"][topic]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return fact["text"], [{"source": record["source"], "updated_at": record["updated_at"], "status": fact["status"]}]
