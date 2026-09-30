import pytest

from backend.services.question_decomposition import split_questions


@pytest.mark.parametrize("question, expected", [
    ("这个课程价格多少？能看多久？有优惠吗？", ["这个课程价格多少", "能看多久", "有优惠吗"]),
    ("价格多少，能看多久，有优惠吗", ["价格多少", "能看多久", "有优惠吗"]),
    ("多少钱以及能看多久，还有优惠吗", ["多少钱", "能看多久", "优惠吗"]),
    ("我是零基础，课程学什么？能看多久？", ["我是零基础，课程学什么", "能看多久"]),
    ("学过Python和ROS，想就业", ["学过Python和ROS，想就业"]),
    ("想学机械臂，推荐课程", ["想学机械臂，推荐课程"]),
    ("想学机械臂。没有硬件。", ["想学机械臂。没有硬件。"]),
    ("这个课程价格多少？", ["这个课程价格多少？"]),
    ("没有什么基础，课程学什么？", ["没有什么基础，课程学什么？"]),
    ("价格？有效期？优惠？", ["价格", "有效期", "优惠"]),
    ("价格多少？我是零基础，课程学什么，能看多久？", ["价格多少", "我是零基础，课程学什么", "能看多久"]),
])
def test_split_explicit_questions_preserves_profile_statements(question, expected):
    assert split_questions(question) == expected
