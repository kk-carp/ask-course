"""生成可复制的人工咨询摘要，不发送给外部顾问。"""

from backend.services.consultation_service import FIELDS


def build_handoff_summary(*, profile: dict, course_id: str | None, candidates: list[str], question: str) -> str:
    labels = {"basis": {"none": "零基础", "basic": "有基础", "experienced": "有项目经验"},
              "hardware": {"yes": "有练习硬件", "no": "没有练习硬件", "unknown": "硬件未明确"}}
    values = {}
    for key in FIELDS:
        value = profile.get(key)
        values[key] = labels.get(key, {}).get(value, str(value) if value is not None else "尚未提供")
    return "\n".join([
        "课程咨询摘要", f"正在咨询课程：{course_id or '尚未选择'}",
        f"候选课程：{'、'.join(candidates) or '尚无候选'}",
        f"学习目标：{values['goal']}", f"现有基础：{values['basis']}",
        f"练习条件：{values['hardware']}", f"每周投入：{values['weekly_hours']}",
        f"项目完成期限：{values['deadline']}",
        f"需要顾问确认的问题：{question}",
    ])
