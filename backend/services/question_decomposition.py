"""拆分明确的并列问题，保留陈述与其相邻问题的上下文。"""

import re

_SENTENCE = re.compile(r"(?<=[？?！!。；;\n])")
_CLAUSE = re.compile(r"[，,]|(?:以及|另外|还有|同时|并且)")
_QUESTION = re.compile(
    r"[？?]|吗|怎么|(?<!没)(?<!没有)什么|多少|多久|几(?:天|年|月|节|次|小时)|"
    r"哪些|哪门|哪里|是否|如何|能否|有没有|可不可以"
)


def split_questions(question: str) -> list[str]:
    """仅在存在多个明确问题时拆分；选课画像陈述不会被拆成问题。"""
    sentences = [text.strip() for text in _SENTENCE.split(question) if text.strip()]
    parts: list[str] = []
    for sentence in sentences:
        clauses = [text.strip() for text in _CLAUSE.split(sentence) if text.strip()]
        if sum(bool(_QUESTION.search(text)) for text in clauses) < 2:
            parts.append(sentence)
            continue
        prefix: list[str] = []
        sentence_parts: list[str] = []
        for clause in clauses:
            if _QUESTION.search(clause):
                sentence_parts.append("，".join([*prefix, clause]))
                prefix.clear()
            elif sentence_parts:
                sentence_parts[-1] += f"，{clause}"
            else:
                prefix.append(clause)
        parts.extend(sentence_parts)
    # 句号分开的自我介绍、短答等仍属于同一轮，不当作多个问句。
    if len(parts) < 2 or sum(bool(_QUESTION.search(text)) for text in parts) < 2:
        return [question.strip()]
    combined: list[str] = []
    prefix = []
    for part in parts:
        if _QUESTION.search(part):
            combined.append("".join(prefix) + part)
            prefix.clear()
        else:
            prefix.append(part)
    if prefix:
        combined[-1] += "".join(prefix)
    return [part.strip("？?！!。；;\n ") for part in combined]
