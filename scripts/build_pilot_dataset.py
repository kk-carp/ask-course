"""生成真实课程 ID 的验收案例；事实期望来自本地资料，结果不提交仓库。"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOPICS = {
    "outline": ["课程目录有哪些？", "课程大纲是什么？", "具体学什么？", "主要学哪些内容？"],
    "audience": ["这门课适合谁？", "课程适用人群是什么？", "主要面向谁？"],
    "basis": ["基础要求是什么？", "零基础能学吗？"],
    "hardware": ["没有真机能学吗？", "设备要求是什么？", "需要自备硬件吗？"],
    "validity": ["能看多久？", "课程有效期是多久？"],
    "certificate": ["有证书吗？", "结业证书如何取得？"],
    "schedule": ["怎么上课？", "授课方式是什么？"],
    "price": ["价格多少？", "这门课多少钱？"],
}


def build():
    facts = json.loads((ROOT / "data/course_facts.json").read_text(encoding="utf-8"))
    cases = []
    for cid in ("42", "43", "99"):
        for topic, questions in TOPICS.items():
            for index, question in enumerate(questions, 1):
                status = "official" if topic == "price" else facts[cid]["facts"][topic]["status"]
                cases.append({"id": f"{cid}-{topic}-{index}", "course_id": cid, "topic": topic,
                              "question": question, "expected_hit": status not in {"unknown", "conflict"},
                              "require_sources": True, "expected_fact_status": status,
                              "expected_source": f"/detail/{cid}" if topic == "price" else facts[cid]["source"],
                              "forbidden_phrases": ["保证就业", "保证拿证", "百分百", "可以永久观看"]})
        cases.extend([
            {"id": f"{cid}-triple", "course_id": cid, "question": "价格多少？能看多久？有优惠吗？", "intent": "multi_question", "require_sources": True},
            {"id": f"{cid}-advisor", "course_id": cid, "question": "找课程顾问", "intent": "advisor", "expected_owner_topic_key": cid},
            {"id": f"{cid}-negotiation", "course_id": cid, "question": "还能便宜一点吗？", "intent": "commercial", "expected_owner_topic_key": cid},
        ])
    cases.extend([
        {"id": "no-hardware-dialogue", "turns": [
            {"question": "想学机械臂，推荐课程", "expect_course": "99"},
            {"question": "有一定基础，学过 Python 和 ROS", "expect_course": "99"},
            {"question": "没有机械臂硬件", "expect_course": "99"},
            {"question": "没有真机能学吗？", "intent": "course_info", "require_sources": True},
        ]},
        {"id": "cross-page-dialogue", "course_id": "43", "turns": [
            {"question": "想学机械臂", "expect_course": "99"},
            {"question": "这门课价格多少？", "course_id": "42", "intent": "course_info", "require_sources": True},
            {"question": "找人工", "course_id": "42", "expected_owner_topic_key": "99"},
        ]},
        {"id": "compare-and-ordinal", "turns": [
            {"question": "具身智能有哪些相关课程？", "intent": "recommend"},
            {"question": "这两门有什么区别？", "intent": "compare", "require_sources": True},
            {"question": "第二门的价格多少？", "intent": "course_info", "require_sources": True},
        ]},
        {"id": "invalid-course", "course_id": "999999", "question": "价格多少？", "expected_hit": False, "no_purchase": True},
        {"id": "invalid-purchase", "path": "/courses/999999/purchase", "expected_http": 404},
    ])
    output = ROOT / "data/eval/pilot_gold.jsonl"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in cases), encoding="utf-8")
    print(f"Generated {len(cases)} cases")


if __name__ == "__main__":
    build()
