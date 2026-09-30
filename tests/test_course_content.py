from backend.domain.course_content import (
    inspect_course_content,
    validate_course_content,
)

COMPLETE_COURSE = """
# 四足机器人巡检

## 适用人群
适合具备 Python 和 Linux 基础、希望进入机器人巡检方向的学员。

## 课程目录
包含安全规范、运动控制、任务规划、环境感知和现场部署五个模块。

## 学习安排
共六周，每周学习六小时，包含仿真实验、答疑和一次现场作业。

## 结业证书
完成全部作业并通过项目评审后，按课程规则颁发结业证书。
"""


def test_complete_course_content_passes() -> None:
    report = validate_course_content(COMPLETE_COURSE)

    assert report.complete is True
    assert report.missing_sections == ()


def test_missing_section_is_reported() -> None:
    report = inspect_course_content(COMPLETE_COURSE.replace("## 结业证书", "## 其他说明"))

    assert report.complete is False
    assert report.missing_sections == ("结业证书",)


def test_placeholder_content_is_rejected() -> None:
    report = inspect_course_content(COMPLETE_COURSE + "\nTODO：补充价格。")

    assert report.complete is False
    assert "todo" in report.placeholder_markers
