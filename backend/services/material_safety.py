"""资料发布前的保守规则检查；报告不携带命中原文，人工审核仍不可省略。"""

import re
from collections import Counter

REVIEW_CHECKS = ("public_source", "no_sensitive_data", "business_verified", "no_embedded_instructions")
_RULES = {
    "private_key": r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    "credential": r"(?i)(?:\bsk-[a-z0-9_-]{16,}|\bAKIA[A-Z0-9]{16}\b|(?:api[_-]?key|secret[_-]?key|access[_-]?token|password|密码|密钥)\s*[=:：]\s*[\"']?[a-z0-9_+/=-]{8,})",
    "personal_id": r"(?<!\d)[1-9]\d{5}(?:19|20)\d{9}[\dXx](?!\d)",
    "personal_phone": r"(?<!\d)1[3-9]\d{9}(?!\d)",
    "private_business": r"内部专用|仅供内部|不得外传|未公开报价|底价|合同原件|保密协议|internal\s+only|confidential",
    "embedded_instruction": r"忽略.{0,12}(?:指令|规则|提示)|泄露.{0,12}(?:密钥|提示词)|ignore\s+(?:all\s+)?(?:previous|system)\s+instructions|reveal\s+(?:the\s+)?system\s+prompt",
}
_COMPILED = {key: re.compile(value, re.IGNORECASE) for key, value in _RULES.items()}


def inspect_material(parts) -> dict:
    counts = Counter()
    # Scan the title and all indexed chunks; rules do not replace original-file review.
    text = "\n".join(parts)
    for code, pattern in _COMPILED.items():
        counts[code] += sum(1 for _ in pattern.finditer(text))
    findings = [{"code": code, "count": count} for code, count in counts.items() if count]
    return {"passed": not findings, "findings": findings,
            "manual_checks": list(REVIEW_CHECKS), "rule_version": "2026-10-10"}
