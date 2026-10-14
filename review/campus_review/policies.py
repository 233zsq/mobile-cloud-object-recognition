"""Versioned profile selection and pure AI judgments, separate from jobs."""

import re
from werkzeug.exceptions import BadRequest
from . import ai_review as ai

POLICY = "strict-crosscheck-v2"
MAX_POLICY = "max-direct-v1"
MAX_MODEL = "qwen3.8-max-0902"
CASCADE_POLICY = "flash-max-cascade-v1"
FLASH_MODEL = "qwen3.8-flash"


def profiles(primary, policy=None, *, strict_policy=POLICY):
    if policy == CASCADE_POLICY:
        if primary != FLASH_MODEL:
            raise BadRequest("Flash优先策略需要选择Qwen3.8-Flash")
        return [
            ai.Profile(FLASH_MODEL, "campus-ai-review-v6"),
            ai.Profile(MAX_MODEL, "campus-ai-review-v6"),
        ]
    if policy not in (None, "", strict_policy, MAX_POLICY):
        raise BadRequest("未知的自动审核策略")
    if (
        policy == MAX_POLICY
        and primary != MAX_MODEL
        or policy == strict_policy
        and primary == MAX_MODEL
    ):
        raise BadRequest("审核策略与模型不匹配")
    if primary == MAX_MODEL:
        return [ai.Profile(MAX_MODEL, "campus-ai-review-v6")]
    if primary not in ("qwen3.8-flash", "qwen3-vl-plus-2025-12-19"):
        raise BadRequest("先选择已校验的视觉分流模型")
    return [
        ai.Profile(primary, "campus-ai-review-v4"),
        ai.Profile("qwen3-vl-plus-2025-12-19", "campus-ai-review-v3"),
        ai.Profile("qwen3-vl-plus-2025-12-19", "campus-ai-review-v5"),
    ]


def policy_for(selected, *, strict_policy=POLICY):
    if selected == profiles(FLASH_MODEL, CASCADE_POLICY):
        return CASCADE_POLICY
    return (
        MAX_POLICY
        if selected == [ai.Profile(MAX_MODEL, "campus-ai-review-v6")]
        else strict_policy
    )


def candidate(result, category, policy=None):
    """No self-reported confidence; crops and uncertain labels stay human."""
    if not result or result.get("bbox") is not None:
        return None
    decision, actual, flags = (
        result.get("decision"),
        result.get("category_id"),
        result.get("flags"),
    )
    if policy in (MAX_POLICY, CASCADE_POLICY):
        # The expansion pilot exposed shelf/shop scenes being called clear
        # books. Escalate these contradictory passes, then keep unresolved Max
        # passes human; never turn a text heuristic into an automatic rejection.
        words = str(result.get("subject", "")) + " " + str(result.get("reason", ""))
        if (
            decision == "pass"
            and category == 2
            and (
                re.search(
                    r"书架|书店|书库|图书馆|大量|密集|成排|堆叠|堆满|bookshelf|bookcase|bookshop|bookstore|library",
                    words,
                    re.I,
                )
                or re.search(
                    r"^(?:一位|一个|A |An |The )?(?:人物|女人|男人|女子|男子|女孩|男孩|person\b|woman\b|man\b|girl\b|boy\b)|阅读的(?:女子|男子|人物)",
                    str(result.get("subject", "")),
                    re.I,
                )
            )
        ):
            return None
        if policy == CASCADE_POLICY and re.search(
            r"疑似|可能|用途不明|不确定|无法确认|无法确定",
            str(result.get("subject", "")) + " " + str(result.get("reason", "")),
        ):
            return None
        # Trust the validated primary decision, not consensus or keyword votes.
        # Valid in-scope photos carrying a different label still need relabelling.
        if (
            decision == "pass"
            and type(actual) is int
            and actual == category
            and flags == []
        ):
            return "approved"
        if (
            decision == "reject"
            and (actual is None or type(actual) is int and actual == category)
            and isinstance(flags, list)
            and flags
            and set(flags) <= ai.FLAGS
        ):
            return "rejected"
        return None
    words = str(result.get("subject", "")) + " " + str(result.get("reason", ""))
    if re.search(r"疑似|可能|用途不明|不确定|无法确认|无法确定|主要主体之一", words):
        return None
    if (
        decision == "pass"
        and type(actual) is int
        and actual == category
        and flags == []
    ):
        if re.search(
            r"人物|人群|人身|人体|由人|人背|人像|人脸|会议|街景|书架|整机|局部|扫描|包装|场景|截断|出画|切掉|未完整|大量|密集|数量多|成排|多种|电子设备|主要物品之一|主体之一",
            words,
        ):
            return None
        return "approved"
    if (
        decision == "reject"
        and actual is None
        and isinstance(flags, list)
        and flags
        and set(flags) <= {"out_of_scope", "illustration"}
    ):
        return "rejected"
    return None


def needs_max(result, category):
    """Only unresolved judgments escalate; edits and wrong labels stay human."""
    return (
        result.get("bbox") is None
        and result.get("decision") != "crop"
        and (
            result.get("category_id") is None
            or type(result.get("category_id")) is int
            and result["category_id"] == category
        )
        and candidate(result, category, CASCADE_POLICY) is None
    )


def decide(results, category, policy=None):
    if policy == CASCADE_POLICY:
        if len(results) == 1:
            return candidate(results[0], category, policy)
        if len(results) == 2 and needs_max(results[0], category):
            return candidate(results[1], category, policy)
        return None
    choices = [candidate(result, category, policy) for result in results]
    required = 1 if policy == MAX_POLICY else 3
    return (
        choices[0]
        if len(choices) == required and choices[0] and len(set(choices)) == 1
        else None
    )
