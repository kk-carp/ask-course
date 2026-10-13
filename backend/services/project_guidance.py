"""把宽泛项目目的转成可探索方向；选题建议不代表课程适配或结果承诺。"""

import re

_OPEN_SEARCH = re.compile(r"推荐|哪门|哪些课|有哪些|帮我选|有什么课|还不知道|选什么方向|什么方向")
_JUDGMENT = re.compile(
    r"适合|适不适合|能不能|能否|可不可以|可以当|能当|有没有用|有用吗|有帮助|值得|能用|可以用|拿来|当作|作为"
)
_USES = (
    ("保研", "保研"),
    ("毕业设计", "毕业设计"),
    ("毕设", "毕业设计"),
    ("竞赛", "竞赛"),
    ("留学", "留学申请"),
    ("找工作", "求职"),
    ("求职", "求职"),
    ("就业", "求职"),
    ("面试", "面试展示"),
)
_PERSONAL_FIT = re.compile(r"适合我吗|适不适合我|我适合吗|适合我学吗")
_USE_GOAL = {
    "保研": "保研项目",
    "毕业设计": "毕业设计项目",
    "竞赛": "竞赛项目",
    "留学申请": "留学申请项目",
    "求职": "求职项目",
    "面试展示": "面试展示项目",
}
_USE_LIMIT = {
    "保研": "课程本身不能决定录取。",
    "毕业设计": "学校是否认可题目，还要按所在院系的要求确认。",
    "竞赛": "课程本身不能决定比赛结果。",
    "求职": "课程本身不能决定是否录用。",
    "留学申请": "课程本身不能决定录取。",
    "面试展示": "课程本身不能决定面试结果。",
}


def is_project_goal(text: str) -> bool:
    return bool(re.search(r"保研|毕设|毕业设计|竞赛|(?:想|希望|准备|打算).{0,8}项目", text))


def course_use_labels(text: str) -> tuple[str, ...]:
    """问句已经点明用途，并且在做判断，而不是在索要课单。"""
    if not text or _OPEN_SEARCH.search(text) or not _JUDGMENT.search(text):
        return ()
    found: list[str] = []
    for needle, label in _USES:
        if needle in text and label not in found:
            found.append(label)
    return tuple(found)


def course_use_label(text: str) -> str | None:
    labels = course_use_labels(text)
    return labels[0] if labels else None


def course_use_goal(text: str) -> str | None:
    labels = course_use_labels(text)
    if not labels:
        return None
    if len(labels) == 1:
        return _USE_GOAL[labels[0]]
    return "或".join(labels) + "项目"


def personal_fit_question(text: str) -> bool:
    """在问当前这门课是否适合自己，没有另外点明用途。"""
    return bool(text) and course_use_label(text) is None and not _OPEN_SEARCH.search(text) and bool(_PERSONAL_FIT.search(text))


def answer_course_use(title: str, description: str, label: str) -> str:
    intro = f"官网介绍：{description}" if description else "官网介绍没有写明可展示的项目内容。"
    return (
        f"可以把「{title}」作为{label}时一段可演示、可复盘的实践经历。{intro}\n\n"
        f"选题参考：{project_idea(title, description)}\n\n"
        f"{_USE_LIMIT[label]}评审看的是你能不能讲清任务过程、实验记录和结果。"
    )


def answer_personal_fit(title: str, description: str) -> str:
    intro = f"官网介绍：{description}" if description else "官网介绍没有写明适用条件。"
    return (
        f"「{title}」是否适合你，要看基础和练习条件。{intro}\n\n"
        "你目前的编程和机器人基础如何？"
    )


def project_idea(title: str, description: str = "") -> str:
    """一门课只写能先做出来的一件事。"""
    content = title + description
    if "机械臂" in content:
        return "做一段机械臂操作演示，记下流程、结果和失败案例。"
    if any(word in content for word in ("巡检", "导航", "四足")):
        return "做一段导航或巡检演示，记下任务流程，并比较实验结果。"
    if "大模型" in content:
        return "做一段大模型应用演示，用测试案例和对比实验说明效果。"
    if re.search(r"ROS", content, re.I):
        return "沿着 ROS2 通信做一段可复现的入门实验。"
    if "嵌入式" in content:
        return "做一段嵌入式控制演示，记下接线和运行结果。"
    return "从公开内容里选一个小任务，做出可复现的实验。"


_GOAL_LABELS = {goal: (label,) for label, goal in _USE_GOAL.items()}
_JUDGMENT_LEAD = {
    "保研": "可以。下面几门都能先做成一段能拿出来讲的实践，用来准备保研材料。能不能录取还要看学校，课本身决定不了。",
    "毕业设计": "可以拿来做毕设。下面几门都能先做成一段能演示的实践。这个题目学校认不认可，还要看所在院系。",
    "竞赛": "可以拿来做竞赛准备。下面几门都能先做成一段能演示的实践。课本身决定不了比赛结果。",
    "求职": "可以当成一段求职时能讲的项目经历。下面几门都能先做出来。课本身决定不了能不能被录用。",
    "留学申请": "可以当成申请材料里的一段实践。下面几门都能先做成能演示的小成果。课本身决定不了录取。",
    "面试展示": "可以先做成一段面试时能演示的实践。下面几门都能做出来。课本身决定不了面试结果。",
}


def _labels_from_goal(goal: str) -> tuple[str, ...]:
    if goal in _GOAL_LABELS:
        return _GOAL_LABELS[goal]
    if goal.endswith("项目") and "或" in goal:
        parts = goal.removesuffix("项目").split("或")
        if parts and all(part in _USE_GOAL for part in parts):
            return tuple(parts)
    return ()


def _suitability_lead(labels: tuple[str, ...]) -> str:
    if labels == ("保研", "毕业设计"):
        return (
            "可以。保研材料或毕设选题都可以从一段能演示的实践开始，下面几门课都能先做出来。"
            "能不能录取、题目认不认可，还要看学校和院系。"
        )
    if len(labels) == 1:
        return _JUDGMENT_LEAD[labels[0]]
    names = "或".join("毕设" if label == "毕业设计" else label for label in labels)
    return f"可以。下面几门都能先做成一段能演示的实践，用来准备{names}。具体认不认可，还要看学校或院系的要求。"


def project_guidance(profile: dict) -> str:
    """方向只说一次。还缺的信息由下一问单独提出，不再附清单。"""
    goal = profile.get("goal", "")
    if re.search(r"机械臂|巡检|导航|四足|大模型|ROS|嵌入式", goal, re.I):
        return "可以先做成一个能演示、能复现的小项目。"
    labels = _labels_from_goal(goal)
    if labels and not re.search(r"推荐|还不知道|选什么|有什么", goal):
        return _suitability_lead(labels)
    return "还没定具体题目也可以。下面这些课都能先做成一个可演示的小项目。"
