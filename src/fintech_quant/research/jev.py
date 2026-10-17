"""Jev: an LLM analyst that answers a fixed question set about one stock.

Same division of labour as the "JEV PICKS" desk: cheap deterministic filters run first (Luk
checks, multi-factor score, event NLP, financial trend), then Jev answers fixed questions as JSON,
and deterministic SOFT thresholds turn those answers into support / neutral / veto.

Guardrails:
- Jev sees only the facts packet built here and is told not to use outside or remembered events.
- temperature 0; provider, model, prompt hash, packet hash and the raw reply are recorded.
- The same packet is answered once and then served from the record (no repeat cost).
- Jev is advisory. It never changes the counted strategy, the shadow pool or any evidence, and it
  cannot upgrade a technical "avoid" into an entry. LLM judgments cannot be backtested honestly
  (look-ahead), so they are only ever evaluated forward.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import ssl
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping


QUESTIONS: tuple[dict[str, object], ...] = (
    {
        "id": "negative_event_risk",
        "labels": ["无", "轻微", "明显", "严重"],
        "question": "已披露信息中，是否存在可能在未来一个月显著压制股价的负面事件（减持、问询、处罚、业绩下修、稀释等）？0=没有，1=非常严重",
        "max": 0.55,
    },
    {
        "id": "earnings_support",
        "labels": ["明显恶化", "偏弱", "持平", "较强", "强劲"],
        "question": "只看最近几期财报本身，盈利与成长趋势有多强？0=明显恶化，1=强劲",
        "min": 0.45,
    },
    {
        "id": "catalyst_quality",
        "labels": ["没有或不可信", "较弱", "中等", "强"],
        "question": "近期正面催化剂是否真实、可验证、可持续，而不是传闻或一次性事件？0=没有或不可信，1=强",
    },
    {
        "id": "crowding",
        "labels": ["冷清", "正常", "偏热", "极度拥挤"],
        "question": "关注度与情绪是否过热拥挤（研报一致看多、散户追问、传闻驱动）？0=冷清，1=极度拥挤",
        "max": 0.75,
    },
    {
        "id": "setup_consistency",
        "labels": ["明显矛盾", "部分矛盾", "大体一致", "高度一致"],
        "question": "技术形态（Luk 四步）与基本面、消息面是否相互印证？0=明显矛盾，1=高度一致",
        "min": 0.40,
    },
)
SYSTEM_PROMPT = (
    "你是 Jev，一名 A 股研究助理。只能依据用户提供的资料包作答，不得使用资料包以外的信息，"
    "也不得使用你记忆中资料包日期之后的事件。资料不足时给 0.5 并在理由中说明。"
    "严格只输出 JSON，不要输出其他文字，格式："
    '{"answers": {"<问题id>": {"score": 0到1的小数, "reason": "不超过60字"}}, '
    '"stance": "support|neutral|avoid", "summary": "不超过120字", "key_risks": ["最多3条"]}。'
    "你的结论仅供研究参考，不构成投资建议。"
)
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5-5"
DEFAULT_DEEPSEEK_MODEL = "deepseek-flash"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"


class JevNotConfigured(RuntimeError):
    pass


Transport = Callable[[str, Mapping[str, str], bytes, float], bytes]


def _ssl_context() -> ssl.SSLContext:
    """Verify TLS against the OS trust store (python.org builds ignore the macOS keychain)."""
    try:
        import truststore

        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:
        pass
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _urllib_transport(url: str, headers: Mapping[str, str], body: bytes, timeout: float) -> bytes:
    request = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")
    with urllib.request.urlopen(request, timeout=timeout, context=_ssl_context()) as response:  # noqa: S310
        return response.read()


def looks_like_secret(value: str) -> bool:
    return value.startswith(("sk-", "sk_", "Bearer ")) or (
        len(value) > 40 and " " not in value and "/" not in value
    )


class LlmClient:
    def __init__(
        self,
        *,
        provider: str,
        api_key: str,
        model: str,
        base_url: str | None = None,
        transport: Transport = _urllib_transport,
        timeout: float = 60.0,
    ) -> None:
        if provider not in {"anthropic", "openai"}:
            raise ValueError("JEV_PROVIDER must be anthropic or openai")
        self.provider = provider
        self.api_key = api_key
        self.model = model
        self.base_url = (
            base_url
            or (
                "https://api.anthropic.com"
                if provider == "anthropic"
                else "https://api.openai.com/v1"
            )
        ).rstrip("/")
        self.transport = transport
        self.timeout = timeout

    def complete(self, system: str, user: str) -> str:
        if self.provider == "anthropic":
            body = {
                "model": self.model,
                "max_tokens": 1500,
                "temperature": 0,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            }
            raw = self.transport(
                f"{self.base_url}/v1/messages",
                {
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json.dumps(body).encode("utf-8"),
                self.timeout,
            )
            payload = json.loads(raw)
            return "".join(
                part.get("text", "")
                for part in payload.get("content", [])
                if part.get("type") == "text"
            )
        body = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        raw = self.transport(
            f"{self.base_url}/chat/completions",
            {"authorization": f"Bearer {self.api_key}", "content-type": "application/json"},
            json.dumps(body).encode("utf-8"),
            self.timeout,
        )
        return str(json.loads(raw)["choices"][0]["message"]["content"])


TYPESAFE_DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"
STANCE_QUESTION = {
    "type": "choice",
    "instructions": "综合资料包，这只股票当前的整体研究倾向是？",
    "criteria": {
        "support": "偏正面，支持关注入场",
        "neutral": "中性，继续观察",
        "avoid": "偏负面，回避",
    },
}


def normalize_jev_model(value: str) -> str:
    """'Jev 1.14' / 'jev-1.14' / 'latest' -> OpenRouter ids such as 'typesafe/jev-1.14'."""
    text = value.strip()
    if "/" in text:
        return text
    lowered = text.lower().replace(" ", "-")
    if "latest" in lowered:
        return "~typesafe/jev-latest"
    version = re.search(r"(\d+\.\d+)", lowered)
    return f"typesafe/jev-{version.group(1)}" if version else "~typesafe/jev-latest"


class JevDecisionClient:
    """TypeSafe Jev (System One) through OpenRouter: typed questions in, probabilities out."""

    provider = "typesafe"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        url: str = TYPESAFE_DECISIONS_URL,
        transport: Transport = _urllib_transport,
        timeout: float = 60.0,
    ) -> None:
        self.api_key, self.model, self.url, self.transport, self.timeout = (
            api_key,
            model,
            url,
            transport,
            timeout,
        )

    def request_body(self, packet: Mapping[str, object]) -> dict[str, object]:
        questions: dict[str, object] = {
            str(q["id"]): {
                "type": "score",
                "instructions": q["question"].split("？")[0] + "？",
                "criteria": q["labels"],
            }
            for q in QUESTIONS
        }
        questions["stance"] = STANCE_QUESTION
        return {"model": self.model, "state": dict(packet), "questions": questions}

    def decide(
        self, packet: Mapping[str, object]
    ) -> tuple[dict[str, object], str, dict[str, object]]:
        raw = self.transport(
            self.url,
            {"authorization": f"Bearer {self.api_key}", "content-type": "application/json"},
            json.dumps(self.request_body(packet), ensure_ascii=False).encode("utf-8"),
            self.timeout,
        )
        payload = json.loads(raw)
        answers = payload.get("answers") or {}
        clean = {}
        for question in QUESTIONS:
            answer = answers.get(question["id"])
            if not isinstance(answer, dict) or not isinstance(answer.get("probabilities"), dict):
                raise ValueError(f"Jev decision is missing probabilities for {question['id']}")
            probabilities = {int(k): float(v) for k, v in answer["probabilities"].items()}
            levels = len(question["labels"])  # type: ignore[arg-type]
            expected = sum(i * p for i, p in probabilities.items()) / max(
                1, sum(probabilities.values())
            )
            top = max(probabilities, key=probabilities.get)
            clean[str(question["id"])] = {
                "score": round(expected / (levels - 1), 4),
                "reason": f"最可能：{question['labels'][top]}（{probabilities[top]:.0%}），置信 {float(answer.get('confidence', 0)):.0%}",  # type: ignore[index]
                "probabilities": {
                    question["labels"][i]: p for i, p in sorted(probabilities.items())
                },  # type: ignore[index]
            }
        stance = answers.get("stance") or {}
        choice = (
            stance.get("choice")
            if stance.get("choice") in {"support", "neutral", "avoid"}
            else "neutral"
        )
        stance_p = dict(stance.get("probabilities") or {})
        parsed = {
            "answers": clean,
            "stance": choice,
            "summary": "Jev 整体倾向："
            + "、".join(
                f"{k} {float(v):.0%}"
                for k, v in sorted(stance_p.items(), key=lambda kv: -float(kv[1]))
            ),
            "key_risks": [
                f"{name}偏高（{clean[qid]['reason'].split('（')[0].removeprefix('最可能：')}）"
                for qid, name in (("negative_event_risk", "负面事件风险"), ("crowding", "拥挤度"))
                if float(clean[qid]["score"]) >= 0.5
            ],
        }
        meta = {
            "served_model": payload.get("model"),
            "usage": payload.get("usage"),
            "id": payload.get("id"),
        }
        return parsed, raw.decode("utf-8") if isinstance(raw, bytes) else str(raw), meta


def client_from_env(env: Mapping[str, str] | None = None) -> LlmClient | JevDecisionClient | None:
    """DeepSeek when DEEPSEEK_API_KEY is set; Anthropic for ANTHROPIC_API_KEY; else OpenAI-compatible."""
    values = os.environ if env is None else env
    if looks_like_secret(values.get("JEV_MODEL", "")):
        raise JevNotConfigured(
            "JEV_MODEL 的值看起来是 API 密钥而不是模型名：请清空或改为模型名（如 deepseek-flash），"
            "并作废这个密钥后放到正确的变量里"
        )
    if (
        re.search(r"jev", values.get("JEV_MODEL", ""), flags=re.I)
        or values.get("JEV_PROVIDER") == "typesafe"
    ):
        if not values.get("OPENROUTER_API_KEY"):
            raise JevNotConfigured("TypeSafe Jev 需要 OPENROUTER_API_KEY")
        return JevDecisionClient(
            api_key=values["OPENROUTER_API_KEY"],
            model=normalize_jev_model(values.get("JEV_MODEL") or "latest"),
        )
    if values.get("DEEPSEEK_API_KEY") and not values.get("JEV_PROVIDER"):
        return LlmClient(
            provider="openai",
            api_key=values["DEEPSEEK_API_KEY"],
            model=values.get("JEV_MODEL") or DEFAULT_DEEPSEEK_MODEL,
            base_url=values.get("JEV_BASE_URL") or DEEPSEEK_BASE_URL,
        )
    provider = values.get("JEV_PROVIDER") or (
        "anthropic" if values.get("ANTHROPIC_API_KEY") else "openai"
    )
    key = values.get("JEV_API_KEY") or values.get(
        "ANTHROPIC_API_KEY" if provider == "anthropic" else "OPENAI_API_KEY"
    )
    if not key:
        return None
    model = values.get("JEV_MODEL") or (DEFAULT_ANTHROPIC_MODEL if provider == "anthropic" else "")
    if not model:
        raise JevNotConfigured("set JEV_MODEL for the OpenAI-compatible provider")
    return LlmClient(
        provider=provider, api_key=key, model=model, base_url=values.get("JEV_BASE_URL")
    )


def config_status(env: Mapping[str, str] | None = None) -> dict[str, object]:
    try:
        client = client_from_env(env)
    except JevNotConfigured as exc:
        return {"configured": False, "reason": str(exc)}
    if client is None:
        return {
            "configured": False,
            "reason": "未设置 DEEPSEEK_API_KEY / OPENROUTER_API_KEY（Jev）/ ANTHROPIC_API_KEY",
        }
    return {"configured": True, "provider": client.provider, "model": client.model}


def build_prompt(packet: Mapping[str, object]) -> str:
    questions = "\n".join(f"- {q['id']}: {q['question']}" for q in QUESTIONS)
    return f"请逐题回答（问题 id 必须原样使用）：\n{questions}\n\n资料包（JSON）：\n{_canonical(packet)}"


def ask_jev(
    packet: Mapping[str, object],
    *,
    client: LlmClient | JevDecisionClient,
    record_dir: Path | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    packet_sha = hashlib.sha256(_canonical(packet).encode("utf-8")).hexdigest()
    decision = isinstance(client, JevDecisionClient)
    question_text = (
        _canonical(client.request_body({})) if decision else SYSTEM_PROMPT + build_prompt({})
    )  # type: ignore[union-attr]
    prompt_sha = hashlib.sha256(question_text.encode("utf-8")).hexdigest()
    record_path = None
    if record_dir is not None:
        record_path = (
            record_dir
            / str(packet.get("as_of", "undated"))
            / record_name(str(packet.get("symbol", "unknown")), packet_sha, client.model)
        )
        if record_path.exists():
            return {**json.loads(record_path.read_text(encoding="utf-8")), "cached": True}
    meta: dict[str, object] = {}
    if decision:
        parsed, reply, meta = client.decide(packet)  # type: ignore[union-attr]
    else:
        reply = client.complete(SYSTEM_PROMPT, build_prompt(packet))  # type: ignore[union-attr]
        parsed = parse_reply(reply)
    record = {
        "schema_version": 1,
        "kind": "jev_judgment",
        "advisory_only": True,
        "symbol": packet.get("symbol"),
        "as_of": packet.get("as_of"),
        "created_at": (now or datetime.now(timezone.utc)).isoformat(),
        "provider": client.provider,
        "model": client.model,
        "prompt_sha256": prompt_sha,
        "packet_sha256": packet_sha,
        "packet": dict(packet),
        "raw_reply": reply,
        **meta,
        **apply_thresholds(parsed, technical_level=str(packet.get("technical_level", ""))),
    }
    if record_path is not None:
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record_path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    return {**record, "cached": False}


def questions_sha() -> str:
    """Hash of everything that defines the questions; changing any wording invalidates old records."""
    definition = _canonical(
        {"questions": list(QUESTIONS), "system": SYSTEM_PROMPT, "stance": STANCE_QUESTION}
    )
    return hashlib.sha256(definition.encode("utf-8")).hexdigest()


def record_name(symbol: str, packet_sha: str, model: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9.-]+", "_", model).strip("_")[:40]
    return f"{symbol}-{packet_sha[:12]}-{questions_sha()[:8]}-{slug}.json"


def parse_reply(reply: str) -> dict[str, object]:
    match = re.search(r"\{.*\}", reply, flags=re.S)
    if not match:
        raise ValueError("Jev reply contained no JSON object")
    payload = json.loads(match.group(0))
    answers = payload.get("answers")
    if not isinstance(answers, dict):
        raise ValueError("Jev reply is missing answers")
    clean = {}
    for question in QUESTIONS:
        answer = answers.get(question["id"])
        if not isinstance(answer, dict) or not isinstance(answer.get("score"), (int, float)):
            raise ValueError(f"Jev reply is missing a numeric score for {question['id']}")
        clean[str(question["id"])] = {
            "score": max(0.0, min(1.0, float(answer["score"]))),
            "reason": str(answer.get("reason", ""))[:120],
        }
    stance = payload.get("stance")
    return {
        "answers": clean,
        "stance": stance if stance in {"support", "neutral", "avoid"} else "neutral",
        "summary": str(payload.get("summary", ""))[:240],
        "key_risks": [str(r)[:80] for r in payload.get("key_risks", [])][:3],
    }


def apply_thresholds(parsed: Mapping[str, object], *, technical_level: str) -> dict[str, object]:
    answers = dict(parsed["answers"])  # type: ignore[arg-type]
    checks = []
    for question in QUESTIONS:
        score = float(answers[str(question["id"])]["score"])
        if "max" in question:
            checks.append(
                {
                    "id": question["id"],
                    "rule": f"max {question['max']}",
                    "score": score,
                    "passed": score <= float(question["max"]),
                }
            )  # type: ignore[arg-type]
        elif "min" in question:
            checks.append(
                {
                    "id": question["id"],
                    "rule": f"min {question['min']}",
                    "score": score,
                    "passed": score >= float(question["min"]),
                }
            )  # type: ignore[arg-type]
        else:
            checks.append({"id": question["id"], "rule": "仅参考", "score": score, "passed": True})
    vetoed = not all(c["passed"] for c in checks) or parsed["stance"] == "avoid"
    judgment = "veto" if vetoed else ("support" if parsed["stance"] == "support" else "neutral")
    if technical_level == "entry":
        combined = {
            "veto": "技术触发，但 Jev 否决：暂不入场",
            "support": "技术触发 + Jev 支持",
            "neutral": "技术触发，Jev 中性",
        }[judgment]
    elif technical_level == "watch":
        combined = "技术面仍在观察，Jev 结论仅作背景"
    else:
        combined = "技术面不支持入场，Jev 不能推翻"
    return {**parsed, "threshold_checks": checks, "judgment": judgment, "combined": combined}


def _canonical(payload: Mapping[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
