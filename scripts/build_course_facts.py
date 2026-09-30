"""从已整理的课程正文生成常见问题事实表；不批准销售资格。"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def section(text: str, heading: str, level: int = 2) -> str:
    match = re.search(rf"^{'#' * level} {re.escape(heading)}\s*$\n(.*?)(?=^#{{1,{level}}} |\Z)", text, re.M | re.S)
    return match.group(1).strip() if match else ""


def build() -> None:
    result = {}
    catalog = []
    for course_id in ("42", "43", "99"):
        path = ROOT / f"data/course_content/{course_id}.md"
        text = path.read_text(encoding="utf-8")
        facts = {}
        for topic, heading in (("audience", "适用人群"), ("schedule", "学习安排"), ("certificate", "结业证书")):
            value = section(text, heading)
            if topic == "schedule":
                value = section(value, "上课流程", 3) or value
            facts[topic] = {"text": value[:1500], "status": "provided"}
        outline = section(text, "课程目录")
        headings = re.findall(r"^#{3,4} (.+)$", outline, re.M)
        facts["outline"] = {"text": "课程目录包括：\n" + "\n".join(f"- {x}" for x in headings), "status": "provided"}
        basis = section(section(text, "适用人群"), "前置知识要求", 3)
        if not basis:
            basis = next((x for x in text.splitlines() if "前置知识要求：" in x), "")
        facts["basis"] = {"text": basis, "status": "provided"}
        hardware = [line for line in text.split("## 补充讲师资料")[0].splitlines() if any(
            marker in line for marker in ("学员无需自带硬件", "**本地仿真**", "**设备需求清晰**", "Q：没有机械臂真机")
        )]
        facts["hardware"] = {
            "text": "\n".join(hardware) or "提供的资料未明确设备要求，需要课程方核实。",
            "status": "provided" if hardware else "unknown",
        }
        validity_match = re.search(r"\*\*Q：课程有效期[^*]*\*\*\s*A[：:]([^\n]+)", text)
        validity = validity_match.group(1) if validity_match else "提供的资料未明确观看期限，需要课程方核实。"
        conflict = "长期有效" in text and bool(re.search(r"购买后\s*1\s*年", text))
        if conflict:
            validity = "观看期限资料存在冲突：常见问题说明「" + validity + "」，宣传亮点又写录屏长期有效。具体期限需要课程顾问确认，目前不能承诺永久观看。"
        facts["validity"] = {"text": validity, "status": "conflict" if conflict else "provided" if validity_match else "unknown"}
        source = re.search(r"^资料来源：(.+)$", text, re.M).group(1)
        updated = datetime.fromtimestamp((ROOT / source).stat().st_mtime, timezone.utc).isoformat()
        result[course_id] = {"source": source, "updated_at": updated, "facts": facts, "reviewer": None}
        catalog.append({"course_id": course_id, "course_name": re.search(r"^# (.+)$", text, re.M).group(1), "content_file": path.relative_to(ROOT).as_posix(), "content_owner": None, "effective_date": None, "status": "active"})
    (ROOT / "data/course_facts.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ROOT / "data/course_catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    build()
