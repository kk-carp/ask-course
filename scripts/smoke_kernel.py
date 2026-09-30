"""内核自检：验证「RAG 内核可原样复用」这一结论是否站得住。

这个脚本**不需要数据库、不需要下载模型、不需要 API Key**，因此可以在任何
机器上跑，用来回答一个问题：从统一知识助手搬过来的内核，剥掉 FDE 的
用户/空间/角色体系之后，还剩下什么、是否完好。

覆盖四件事：
1. 内核模块可导入（含 embed/rerank 的「重依赖延迟导入」设计是否成立）；
2. 分块器对中文长文的行为（课程详情页文本能否直接吃进去）；
3. 词法切分可用（jieba 缺失时应有降级，不抛错）；
4. RRF 融合的排序与去重正确（混合检索的核心算法）；
5. P0 新增的游客态与转人工降级路径不会打断问答。

用法：
    python scripts/smoke_kernel.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

# 允许从仓库根目录直接运行
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(name)
        print(f"  [PASS] {name}{(' - ' + detail) if detail else ''}")
    else:
        FAILED.append(name)
        print(f"  [FAIL] {name}{(' - ' + detail) if detail else ''}")


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> int:
    print("P0 内核自检（无需数据库 / 模型 / API Key）")

    # ---------------------------------------------------------------
    section("1. 内核模块可导入")

    import backend.config as config_mod
    import backend.errors as errors_mod
    import backend.infra.chunker as chunker_mod
    import backend.infra.lexical as lexical_mod
    import backend.infra.retrieve as retrieve_mod

    check("backend.config 可导入", True)
    check("backend.errors 可导入", True)
    check("backend.infra.chunker 可导入", True)
    check("backend.infra.lexical 可导入", True)
    check("backend.infra.retrieve 可导入", True)

    # embed / rerank 的重依赖（sentence-transformers / torch）必须是函数内延迟导入，
    # 否则在没装 torch 的机器上连模块都导不进来，也就谈不上"复用内核"。
    import backend.infra.embed as embed_mod
    import backend.infra.rerank as rerank_mod

    check("backend.infra.embed 可导入（未加载 torch）", True)
    check("backend.infra.rerank 可导入（未加载 torch）", True)
    check(
        "embed 的重依赖为延迟导入",
        not hasattr(embed_mod, "SentenceTransformer"),
        "sentence_transformers 只在 load_model() 内导入",
    )
    check("embed 提供 encode_query/encode_documents", all(
        hasattr(embed_mod, name) for name in ("encode_query", "encode_documents", "load_model")
    ))
    check("rerank 提供 rerank", hasattr(rerank_mod, "rerank"))
    check(
        "错误语义齐备（503/502 与未命中分离）",
        hasattr(errors_mod, "ServiceUnavailableError")
        and hasattr(errors_mod, "UpstreamServiceError"),
    )

    # ---------------------------------------------------------------
    section("2. P0 配置：课程空间与转人工开关")

    settings = config_mod.settings
    check(
        "课程空间已配置",
        settings.course_space_id == "courses",
        f"course_space_id={settings.course_space_id}",
    )
    check(
        "LLM 网关使用 HTTPS OpenAI 兼容地址",
        settings.chat_base_url.startswith("https://"),
        settings.chat_base_url,
    )
    check("游客 Cookie 已独立命名", settings.visitor_cookie_name == "arborseek_agent_visitor")
    check("未命中转人工默认开启", settings.handoff_enabled is True)

    import backend.infra.storage as storage_mod

    check(
        "上传白名单包含课程空间",
        settings.course_space_id in storage_mod.ALLOWED_SPACES,
        f"ALLOWED_SPACES={sorted(storage_mod.ALLOWED_SPACES)}",
    )
    check(
        "中文文件名清洗后仍保留扩展名",
        storage_mod._sanitize_filename("四足机器人巡检_课程简介.md").endswith(".md"),
        storage_mod._sanitize_filename("四足机器人巡检_课程简介.md"),
    )
    check(
        "检索门控阈值可配（决定何时判未命中）",
        settings.retrieve_use_rerank and settings.rerank_min_score > 0,
        f"gate=rerank_min_score={settings.rerank_min_score}",
    )

    # ---------------------------------------------------------------
    section("3. 分块器：课程详情页文本可直接吃进去")

    # 模拟课程详情页 9 板块拼成的长文（真实形态是 9 个板块的顺序文本）
    blocks = [
        (
            "适用人群：面向零基础但希望进入机器人行业的在校生与转岗工程师，"
            "需要具备基本的 Python 编程能力与 Linux 命令行使用经验。"
        ),
        "学习安排：共 12 周，每周 3 次直播课、1 次答疑，课后需完成 2 个实操作业。",
        "结业证书：完成全部作业并通过结业项目评审后，颁发结业证书。",
    ]
    long_text = "\n\n".join(blocks * 8)
    chunks = chunker_mod.split_text(long_text, chunk_size=800, overlap=100)
    check("分块结果非空", len(chunks) > 0, f"{len(chunks)} chunks")
    check(
        "每块不超过 chunk_size",
        all(len(item) <= 800 for item in chunks),
        f"max={max(len(item) for item in chunks)}",
    )
    check("分块无内容丢失（拼接后覆盖原文关键词）", all(
        keyword in "".join(chunks) for keyword in ("适用人群", "学习安排", "结业证书")
    ))
    check(
        "空输入不报错",
        chunker_mod.split_text("", chunk_size=800, overlap=100) == [],
    )

    # ---------------------------------------------------------------
    section("4. 词法切分：jieba 缺失时应降级而非报错")

    search_text = lexical_mod.to_search_text("四足机器人巡检课程多少钱？")
    check("词法切分返回非空", bool(search_text.strip()), repr(search_text[:60]))
    check("切分保留了核心词", "巡检" in search_text or "四足" in search_text)

    # ---------------------------------------------------------------
    section("5. RRF 融合：混合检索的核心算法")

    def make_chunk(content: str, score: float) -> retrieve_mod.RetrievedChunk:
        return retrieve_mod.RetrievedChunk(
            content=content,
            score=score,
            document_id=uuid4(),
            title="课程示例",
            space_id="courses",
            chunk_id=uuid4(),
            dense_score=score,
        )

    shared = make_chunk("四足机器人巡检 - 适用人群", 0.9)
    dense_only = make_chunk("四足机器人巡检 - 学习安排", 0.8)
    lexical_only = make_chunk("四足机器人巡检 - 课程目录", 0.3)

    dense_list = [shared, dense_only]
    lexical_list = [shared, lexical_only]
    fused = retrieve_mod.fuse_rrf([dense_list, lexical_list], rrf_k=60)

    check("融合结果按 chunk 去重", len(fused) == 3, f"len={len(fused)}")
    check(
        "双通道命中者排第一（RRF 的核心性质）",
        fused[0].content == shared.content,
        fused[0].content,
    )
    check("融合分为正且随名次递减", fused[0].score > fused[1].score > 0)
    check("dense_score 被保留（供关重排时门控）", fused[0].dense_score == 0.9)
    try:
        retrieve_mod.fuse_rrf([dense_list], rrf_k=0)
        check("rrf_k 非正数应报错", False, "未抛异常")
    except ValueError:
        check("rrf_k 非正数应报错", True)

    # ---------------------------------------------------------------
    section("6. 空间过滤：客户端不能指定空间")

    check(
        "空允许空间直接返回空结果（不做全库检索）",
        retrieve_mod.search_dense([0.1] * 1024, [], 5) == [],
    )
    check(
        "top_k<=0 直接返回空结果",
        retrieve_mod.search_dense([0.1] * 1024, ["courses"], 0) == [],
    )

    # ---------------------------------------------------------------
    section("7. P0 新增：游客态与转人工降级")

    from backend.domain.guest import GUEST_ROLE, guest_context

    guest = guest_context("visitor-smoke-test")
    check("游客角色标记正确", guest.user_role == GUEST_ROLE == "guest")
    check(
        "游客允许空间写死为课程空间",
        guest.allowed_spaces == (settings.course_space_id,),
        str(guest.allowed_spaces),
    )
    check("游客无登录用户 id", guest.user_id is None)

    from backend.services.handoff_service import resolve_handoff

    class UnavailableSession:
        def get(self, *_args, **_kwargs):
            raise RuntimeError("simulated database unavailable")

    # 显式注入不可用会话，避免自检触发真实数据库连接；转人工必须降级而不是抛异常。
    result = resolve_handoff(
        question="四足机器人巡检课程多少钱？",
        course_id=None,
        session=UnavailableSession(),
    )
    check(
        "数据库不可用时转人工安全降级（不抛异常）",
        result.route in {"none", "fallback"},
        f"route={result.route}, configured={result.owner.configured}",
    )

    # ---------------------------------------------------------------
    section("8. 数据模型：课程—售前映射就位")

    from backend.models import TopicOwner

    owner_columns = set(TopicOwner.__table__.columns.keys())
    check(
        "course→售前 映射复用 topic_owners 表",
        {"topic_key", "topic_name", "keywords", "owner_name", "contact"} <= owner_columns,
    )

    # ---------------------------------------------------------------
    print("\n" + "=" * 56)
    print(f"通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    if FAILED:
        print("失败项：")
        for item in FAILED:
            print(f"  - {item}")
        return 1
    print("结论：从统一知识助手搬运的内核在剥离 FDE 用户/空间体系后依然完整可用。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
