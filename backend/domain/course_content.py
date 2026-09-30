"""课程内容上线前检查：确保最小四板块齐全，并拦截明显占位内容。"""

from __future__ import annotations

import re
from dataclasses import dataclass

REQUIRED_SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "适用人群": ("适用人群", "适合人群", "面向人群", "谁适合学"),
    "课程目录": ("课程目录", "课程大纲", "课程内容", "学习内容"),
    "学习安排": ("学习安排", "课程安排", "课时安排", "学习周期"),
    "结业证书": ("结业证书", "课程证书", "证书说明", "证书"),
}

PLACEHOLDER_MARKERS = (
    "todo",
    "tbd",
    "待补",
    "待确认",
    "占位",
    "替换为",
    "placeholder",
    "lorem ipsum",
)


@dataclass(frozen=True)
class CourseContentReport:
    complete: bool
    found_sections: tuple[str, ...]
    missing_sections: tuple[str, ...]
    placeholder_markers: tuple[str, ...]
    text_chars: int

    @property
    def problems(self) -> tuple[str, ...]:
        items: list[str] = []
        if self.missing_sections:
            items.append("缺少板块：" + "、".join(self.missing_sections))
        if self.placeholder_markers:
            items.append("包含占位内容：" + "、".join(self.placeholder_markers))
        if self.text_chars < 120:
            items.append("有效文本过短（至少 120 字）")
        return tuple(items)

    def error_message(self) -> str:
        return "课程内容未达到 L0 入库标准：" + "；".join(self.problems)


def _normalized_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        line = re.sub(r"^#{1,6}\s*", "", line)
        line = re.sub(r"^[一二三四五六七八九十\d]+[.、）)]\s*", "", line)
        if line:
            lines.append(line.casefold())
    return lines


def inspect_course_content(text: str) -> CourseContentReport:
    """检查课程正文是否具备 L0 最小四板块；不访问数据库。"""
    normalized = (text or "").strip()
    lines = _normalized_lines(normalized)
    found: list[str] = []
    missing: list[str] = []
    for section, aliases in REQUIRED_SECTION_ALIASES.items():
        if any(
            any(line == alias.casefold() or line.startswith(alias.casefold() + "：") for line in lines)
            for alias in aliases
        ):
            found.append(section)
        else:
            missing.append(section)

    folded = normalized.casefold()
    markers = tuple(marker for marker in PLACEHOLDER_MARKERS if marker in folded)
    text_chars = len(re.sub(r"\s+", "", normalized))
    complete = not missing and not markers and text_chars >= 120
    return CourseContentReport(
        complete=complete,
        found_sections=tuple(found),
        missing_sections=tuple(missing),
        placeholder_markers=markers,
        text_chars=text_chars,
    )


def validate_course_content(text: str) -> CourseContentReport:
    """严格校验并返回报告；失败时给运营可直接处理的原因。"""
    report = inspect_course_content(text)
    if not report.complete:
        raise ValueError(report.error_message())
    return report
