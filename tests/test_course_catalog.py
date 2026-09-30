from backend.services.course_catalog_service import (
    OfficialCourse,
    parse_course_list,
    search_related_courses,
)

CATALOG = (
    OfficialCourse("43", "四足机器人无人巡检实训营", "面向巡检场景"),
    OfficialCourse("102", "四足机器人无人巡检实训营 (体验课)", "体验课"),
    OfficialCourse("11", "【实战|就业】机器狗研发实战营", "机器狗研发"),
    OfficialCourse("99", "智能机械臂抓取与操作实训营", "抓取与操作"),
    OfficialCourse("12", "机器人操作系统之认识ROS", "认识 ROS"),
    OfficialCourse("93", "ROS2机器人系统：从节点通信到整机联调", "ROS2"),
    OfficialCourse("28", "具身智能机器狗巡检工作坊", "机器狗巡检"),
    OfficialCourse("40", "WorkBuddy AI 助手实战课程", "AI 助手"),
)


def test_parse_course_list_keeps_id_title_and_description() -> None:
    courses = parse_course_list(
        {
            "data": {
                "courses": [
                    {"id": 43, "title": "四足机器人无人巡检实训营", "description": "面向巡检场景"},
                    {"id": "", "title": "缺 id"},
                    {"title": "缺 id 字段"},
                    {"id": 12, "title": "  机器人操作系统之认识ROS  ", "description": None},
                ]
            }
        }
    )
    assert courses == (
        OfficialCourse("43", "四足机器人无人巡检实训营", "面向巡检场景"),
        OfficialCourse("12", "机器人操作系统之认识ROS", ""),
    )


def test_search_ranks_quadruped_inspection_first() -> None:
    matches = search_related_courses("有没有四足机器人巡检的课？", courses=CATALOG)
    assert [item.course_id for item in matches][:2] == ["43", "102"]


def test_search_matches_ros_token() -> None:
    matches = search_related_courses("想学 ROS 应该报哪门？", courses=CATALOG)
    assert matches
    assert matches[0].course_id == "12"


def test_search_does_not_match_on_generic_course_word() -> None:
    matches = search_related_courses("机械臂抓取有对应课程吗？", courses=CATALOG)
    assert [item.course_id for item in matches] == ["99"]


def test_search_ignores_question_without_course_terms() -> None:
    assert search_related_courses("今天天气怎么样", courses=CATALOG) == []
