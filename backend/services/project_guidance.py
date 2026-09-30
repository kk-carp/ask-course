"""把宽泛项目目的转成可探索方向；选题建议不代表课程适配或结果承诺。"""

import re


def is_project_goal(text: str) -> bool:
    return bool(re.search(r"保研|毕设|毕业设计|竞赛|(?:想|希望|准备|打算).{0,8}项目", text))


def project_idea(title: str, description: str = "") -> str:
    content = title + description
    if "机械臂" in content:
        return "选题参考：机械臂操作演示，记录任务流程、实验结果和失败案例。"
    if any(word in content for word in ("巡检", "导航", "四足")):
        return "选题参考：机器人导航或巡检演示，展示任务流程并比较实验结果。"
    if "大模型" in content:
        return "选题参考：大模型应用演示，用测试案例和对比实验说明效果。"
    return "选题参考：从课程公开内容中选一个小任务，做可演示、可复现的实验。"


def project_guidance(profile: dict) -> str:
    missing = []
    if "basis" not in profile:
        missing.append("编程基础：会不会 Python，是否学过 ROS/ROS2")
    if "hardware" not in profile:
        missing.append("练习条件：可用的电脑，以及是否有机器人硬件")
    if "weekly_hours" not in profile:
        missing.append("时间投入：每周能投入多少小时")
    if "deadline" not in profile:
        missing.append("完成期限：希望什么时候完成项目或参加面试")
    text = (
        "可以先从能演示、能复现的小项目开始，不需要现在就想好具体题目。"
        "下面是可先了解的项目方向，具体难度和实施条件还需确认。"
        "可以先复现一个基础演示，再增加一个对比实验或小改进。"
        "建议准备演示、代码和实验记录，便于展示自己的实践过程。"
    )
    if missing:
        text += "\n为了缩小范围，可以补充：\n" + "\n".join(f"- {item}" for item in missing)
    return text
