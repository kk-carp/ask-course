"""整理 docs 中的首批课程资料，通过现有上传接口入库。

python scripts/import_course_materials.py --check
python scripts/import_course_materials.py --apply
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.config import settings  # noqa: E402
from backend.domain.course_content import validate_course_content  # noqa: E402

COURSE_FILES = {
    "42": "[01] 高校大学生AI大模型企业实战训练营-宣传信息/AI智能体应用开发工程师课程 宣传信息.md",
    "43": "[01] 四足机器人无人巡检实训营-宣传信息/四足机器人无人巡检实训营 宣传信息.md",
    "99": "[01] 智能机械臂抓取与操作实训营-宣传信息/智能机械臂抓取与操作实训营 宣传信息.md",
}
TEACHER_FILE = (
    "[01] 智能机械臂抓取与操作实训营-宣传信息/图片和附件/"
    "刘延东 教师信息（智能机械臂抓取与操作实训营）/刘延东老师介绍.md"
)


def prepare_material(course_id: str, source: Path) -> str:
    """仅规范板块标题并标注资料差异，保留提供的正文。"""
    text = source.read_text(encoding="utf-8")
    for old, new in (
        (r"^#{1,2}\s*四、课程大纲[^\n]*", "## 课程目录"),
        (r"^#{1,2}\s*六、学员画像[^\n]*", "## 适用人群"),
        (r"^#{1,2}\s*七、学习服务与上课流程[^\n]*", "## 学习安排"),
    ):
        text = re.sub(old, new, text, flags=re.MULTILINE)

    provenance = (
        f"课程 ID：{course_id}\n"
        f"资料来源：{source.relative_to(ROOT).as_posix()}\n"
        f"对应官网课程页：https://www.arborseek.com/course/{course_id}/\n"
        "资料类型：用户提供的课程宣传资料；入库不代表完成销售审核。\n\n"
    )
    if course_id in {"43", "99"}:
        note = (
            "资料差异说明：宣传亮点写有录屏长期有效，常见问题写明购买后一年内有效。"
            "两处说法不一致，不能据此承诺永久观看；具体期限需要向课程方核实。"
        )
        # 注释放在原句附近，避免检索只召回长期有效的片段。
        text = re.sub(r"^.*课程录屏长期有效.*$", lambda m: m.group(0) + "\n\n> " + note,
                      text, flags=re.MULTILINE)
        provenance += note + "\n\n"
        certificate = (
            "原宣传资料提到课程结业证书和结业证书颁发说明，"
            "未列出具体考核与颁发条件；这些条件需要向课程方核实。"
        )
    else:
        certificate = (
            "原宣传资料说明课程对接职信网的 AI 智能体应用开发工程师认证体系，"
            "可根据水平选择报考初级、中级或高级。资料未说明购买课程后自动获得证书；"
            "具体报考与获证条件需要向课程方核实。"
        )
    text = provenance + text.rstrip() + "\n\n## 结业证书\n\n" + certificate + "\n"
    if course_id == "99":
        teacher = ROOT / "docs" / TEACHER_FILE
        text += (
            "\n## 补充讲师资料\n\n"
            f"资料来源：{teacher.relative_to(ROOT).as_posix()}\n\n"
            + teacher.read_text(encoding="utf-8")
        )
    validate_course_content(text)
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description="整理并导入课程 42、43、99 的文字资料")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="仅检查资料，不写数据库")
    mode.add_argument("--apply", action="store_true", help="保存规范化正文并入库")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    materials = {
        course_id: prepare_material(course_id, ROOT / "docs" / relative)
        for course_id, relative in COURSE_FILES.items()
    }
    for course_id, text in materials.items():
        print(f"[CHECK] {course_id}: 四个必要板块齐全，{len(text)} 字符", flush=True)
    if args.check:
        return 0

    output = ROOT / "data" / "course_content"
    output.mkdir(parents=True, exist_ok=True)
    with httpx.Client(base_url=args.base_url, trust_env=False, timeout=300) as client:
        login = client.post("/login", json={"username": "p0_admin", "password": settings.demo_password})
        login.raise_for_status()
        if not login.json()["can_manage_documents"]:
            raise RuntimeError("当前账号没有文档管理权限")
        for course_id, text in materials.items():
            target = output / f"{course_id}.md"
            target.write_text(text, encoding="utf-8")
            print(f"[IMPORT] {course_id}: 正在解析并建立索引", flush=True)
            response = client.post(
                "/documents",
                data={"space": settings.course_space_id, "course_id": course_id},
                files={"file": (target.name, target.read_bytes(), "text/markdown")},
            )
            if response.status_code == 409:
                detail = response.json().get("detail", {})
                if isinstance(detail, dict) and detail.get("code") == "duplicate_document":
                    print(f"[SKIP] {course_id}: 相同正文已入库，文档 {detail['existing_id']}", flush=True)
                    continue
            response.raise_for_status()
            document = response.json()
            if document["status"] != "pending":
                raise RuntimeError(f"课程 {course_id} 文档状态：{document['status']}")
            print(f"[PENDING] {course_id}: {document['chunk_count']} 个片段，文档 {document['id']}；请在 /admin 审核发布", flush=True)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
