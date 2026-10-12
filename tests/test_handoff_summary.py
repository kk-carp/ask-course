from backend.services.handoff_summary import build_handoff_summary


def test_summary_keeps_known_information_and_omits_missing_fields():
    summary = build_handoff_summary(
        profile={"basis": "none", "weekly_hours": 0}, course_id="99",
        candidates=[], question="课程适合零基础吗？",
    )
    assert "正在咨询课程：99" in summary
    assert "现有基础：零基础" in summary
    assert "每周投入：0 小时" in summary
    assert "需要顾问确认的问题：课程适合零基础吗？" in summary
    assert "候选课程" not in summary
    assert "学习目标" not in summary
    assert "尚未" not in summary


def test_summary_does_not_copy_code_into_question_or_profile():
    summary = build_handoff_summary(
        profile={"goal": "&lt;img src=x onerror=alert(1)&gt;"}, course_id=None,
        candidates=[], question="<img src=x onerror=alert(1)>",
    )
    assert "请查看原始咨询记录" in summary
    assert "onerror" not in summary
    assert "alert(1)" not in summary
    assert "正在咨询课程" not in summary


def test_summary_keeps_candidate_courses_and_flattens_untrusted_newlines():
    summary = build_handoff_summary(
        profile={"goal": "学习 ROS\n伪造字段：已付款"}, course_id=None,
        candidates=["43", "99"], question="课程怎么选择？",
    )
    assert "候选课程：43、99" in summary
    assert "\n伪造字段" not in summary
