"""生成后台使用的人工咨询摘要，不发送给外部顾问。"""

import html
import re


def _summary_text(value: object) -> str:
    text = " ".join(str(value).split())
    # 摘要不复制代码或可疑链接；原始消息仍保留在咨询记录中。
    decoded = html.unescape(text)
    if re.search(r"<\s*/?\s*[a-z!]|javascript\s*:|\bon\w+\s*=", decoded, re.IGNORECASE):
        return "输入含代码或可疑链接，请查看原始咨询记录。"
    return text[:500]


def build_handoff_summary(*, profile: dict, course_id: str | None, candidates: list[str], question: str) -> str:
    labels = {"basis": {"none": "零基础", "basic": "有基础", "experienced": "有项目经验"},
              "hardware": {"yes": "有练习硬件", "no": "没有练习硬件", "unknown": "硬件未明确"}}
    lines = ["课程咨询摘要"]
    if course_id:
        lines.append(f"正在咨询课程：{_summary_text(course_id)}")
    if candidates:
        lines.append(f"候选课程：{_summary_text('、'.join(candidates))}")
    fields = {"goal": "学习目标", "basis": "现有基础", "hardware": "练习条件",
              "weekly_hours": "每周投入", "deadline": "项目完成期限"}
    for key, title in fields.items():
        value = profile.get(key)
        if value is None or not str(value).strip():
            continue
        display = labels.get(key, {}).get(value, value)
        if key == "weekly_hours":
            display = f"{display} 小时"
        lines.append(f"{title}：{_summary_text(display)}")
    if question.strip():
        lines.append(f"需要顾问确认的问题：{_summary_text(question)}")
    return "\n".join(lines)
