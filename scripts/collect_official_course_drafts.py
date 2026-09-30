"""从官网公开课程详情提取现成文字，保存为待运营审核的草稿。

不会写入 approved_courses.json、知识库或灰度配置，也不会下载图片。
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parents[1]
DETAIL_URL = "https://arboradmin.saikr.com/miniapp/course/detail"
COURSE_ID = re.compile(r"^[1-9]\d{0,11}$")


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.image_count = 0
        self.hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.hidden_depth += 1
        elif tag == "img":
            self.image_count += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.hidden_depth:
            self.hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth and data.strip():
            self.parts.append(data.strip())

    def text(self) -> str:
        return "\n".join(self.parts)


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _features(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    return [
        {"title": title, "content": _text(item.get("content"))}
        for item in value
        if isinstance(item, dict) and (title := _text(item.get("title")))
    ]


def collect(client: httpx.Client, course_id: str) -> dict:
    if not COURSE_ID.fullmatch(course_id):
        raise ValueError(f"无效课程 ID：{course_id}")
    api_url = f"{DETAIL_URL}/{course_id}"
    response = client.get(api_url)
    response.raise_for_status()
    payload = response.json()
    course = payload.get("data", {}).get("course") if isinstance(payload, dict) else None
    if not isinstance(course, dict) or str(course.get("id")) != course_id:
        raise ValueError(f"{course_id} 官网详情没有返回对应课程")

    full = _VisibleText()
    full.feed(_text(course.get("full_description")))
    h5 = _VisibleText()
    h5.feed(_text(course.get("h5_description")))
    return {
        "course_id": course_id,
        "review_status": "draft",
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "source_url": f"https://www.arborseek.com/course/{course_id}",
        "api_url": api_url,
        "title": _text(course.get("title")),
        "subtitle": _text(course.get("subtitle")),
        "description": _text(course.get("description")),
        "course_features": _features(course.get("course_features")),
        "full_description_text": full.text(),
        "full_description_image_count": full.image_count,
        "h5_description_text": h5.text(),
        "h5_description_image_count": h5.image_count,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="采集官网课程现有文字，供运营审核")
    parser.add_argument("course_ids", nargs="+", help="官网数字课程 ID")
    parser.add_argument(
        "--output-dir", type=Path, default=ROOT / "data" / "official_course_drafts"
    )
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.relative_to(ROOT)
    output_dir.mkdir(parents=True, exist_ok=True)

    with httpx.Client(timeout=10, follow_redirects=False) as client:
        for course_id in args.course_ids:
            row = collect(client, course_id)
            path = output_dir / f"{course_id}.json"
            path.write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(
                f"{course_id}: {path} | 简介 {len(row['description'])} 字，"
                f"详情文本 {len(row['full_description_text'])} 字，"
                f"详情图片 {row['full_description_image_count']} 张"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
