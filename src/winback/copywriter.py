"""Where the AI loop's new subjects and bodies come from: the stand-in writer's prewritten list, or the real
writer and judge on OpenRouter (#13).

The loop asks a copywriter for the next challenger part: given the champion it will be tested against, the
lessons so far (the playbook's conclusions) and which part to change, the copywriter returns a variant with
a hypothesis and a hidden quality, or nothing when it has no more.

The real copywriter writes with an LLM, checks every draft against the fact sheet and the sending rules (a
draft that fails is rewritten, never sent), and asks a judge, a different model, to rate how appealing it is
to an Idle merchant. The rating, against your first draft's, becomes the variant's hidden quality, plus noise:
the judge stands in for merchants and is not treated as always right. Each challenger is written and judged
once per run and shared by every replay, so a 200-replay run makes a few dozen calls, not thousands.
"""

import json
import math
import random
import re
import urllib.error
import urllib.request
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from winback.settings import Email, FactSheet, Settings, Variant, WriterSettings

OPENROUTER = "https://openrouter.ai/api/v1/chat/completions"
DECISIONS = "https://openrouter.ai/api/alpha/decisions"
STAND_IN = "stand-in writer"
IDLE_MERCHANT = "A merchant who signed up to a Shopify app that clones a store to start from, but has not started a draft yet."
# The judge's scale, from 1 to 10.
APPEAL_LEVELS = [
    "1: would ignore it",
    "2: very unlikely to act",
    "3: unlikely to act",
    "4: might glance at it",
    "5: as likely as not",
    "6: somewhat likely to act",
    "7: likely to act",
    "8: very likely to act",
    "9: almost certain to act",
    "10: would certainly act",
]

Post = Callable[[str, dict[str, Any], str], dict[str, Any]]


class Copywriter(Protocol):
    name: str

    def challenger(self, slot: str, champion: Email, lessons: list[str], nth: int) -> Variant | None:
        """The nth new part for this slot ("subject" or "body") in this replay, written against this champion."""
        ...

    def summary(self) -> list[str]:
        """What the report says about who wrote and judged, and what it cost; nothing for the stand-in writer."""
        ...


@dataclass
class StandIn:
    """The stand-in writer: the prewritten subjects and bodies, in order, with their placeholder qualities."""

    settings: Settings
    name: str = STAND_IN

    def challenger(self, slot: str, champion: Email, lessons: list[str], nth: int) -> Variant | None:
        waiting = self.settings.prewritten_subjects if slot == "subject" else self.settings.prewritten_bodies
        return waiting[nth] if nth < len(waiting) else None

    def summary(self) -> list[str]:
        return []


def problems(slot: str, text: str, cta: str, facts: FactSheet, writer: WriterSettings, placeholders: set[str]) -> list[str]:
    """Why a draft can't be sent, if it can't: a number or price not on the fact sheet, a banned phrase, a
    subject posing as a reply or forward or too long, or a placeholder the app can't fill."""
    words, found = f"{text} {cta}", []
    known_numbers = {n for fact in facts.facts for n in re.findall(r"\d+(?:\.\d+)?", fact)}
    for number in re.findall(r"\d+(?:\.\d+)?", re.sub(r"\{[a-z_]+\}", "", words)):
        if number not in known_numbers:
            found.append(f"the number {number} is not on the fact sheet")
    for phrase in facts.banned_phrases:
        if phrase.lower() in words.lower():
            found.append(f'it contains the banned phrase "{phrase}"')
    if slot == "subject" and re.match(r"\s*(re|fwd?)\s*:", text, re.I):
        found.append("the subject pretends to be a reply or a forward")
    if slot == "subject" and len(text) > writer.subject_max_characters:
        found.append(f"the subject is longer than {writer.subject_max_characters} characters")
    if slot == "body" and not cta.strip():
        found.append("the body has no button text")
    for name in set(re.findall(r"\{[a-z_]+\}", words)) - placeholders:
        found.append(f"{name} is not a placeholder the app can fill")
    if not text.strip():
        found.append("it is empty")
    return found


class Writer(Protocol):
    model: str

    def write(self, slot: str, champion: Email, lessons: list[str], tried: list[str], feedback: list[str]) -> tuple[str, str, str]:
        """A new subject (cta empty) or body with its button, and its hypothesis."""
        ...


class Judge(Protocol):
    model: str

    def rate(self, slot: str, text: str, cta: str) -> float:
        """How appealing this part is to an Idle merchant, from 1 to 10."""
        ...


@dataclass
class Spend:
    calls: int = 0
    cost: float = 0.0  # in dollars, as OpenRouter reports it
    rejected: list[str] = field(default_factory=list)  # every draft that failed a check, and why


class AiCopywriter:
    """The real writer and judge behind one interface, with the checks in front and a cache shared by every replay."""

    def __init__(self, settings: Settings, writer: Writer, judge: Judge, spend: Spend | None = None) -> None:
        if writer.model == judge.model:
            raise ValueError(f"The writer and the judge must be different models, not both {writer.model}")
        self.settings, self.writer, self.judge = settings, writer, judge
        self.name = f"AI writer ({writer.model})"
        self.spend = spend or Spend()  # shared with the writer and the judge, which add what each call cost
        self.cache: dict[tuple[str, str, str, int], Variant | None] = {}
        self.ratings: dict[tuple[str, str, str], float] = {}
        draft = settings.first_drafts["idle"]
        self.placeholders = {p for e in settings.first_drafts.values() for p in re.findall(r"\{[a-z_]+\}", f"{e.subject} {e.body} {e.cta}")}
        self.reference = {"subject": self._rating("subject", draft.subject, ""), "body": self._rating("body", draft.body, draft.cta)}

    def challenger(self, slot: str, champion: Email, lessons: list[str], nth: int) -> Variant | None:
        key = (slot, champion.subject, champion.body, nth)
        if nth >= self.settings.writer.challengers_per_part:
            return None
        if key not in self.cache:
            self.cache[key] = self._write(slot, champion, lessons, nth)
        return self.cache[key]

    def _write(self, slot: str, champion: Email, lessons: list[str], nth: int) -> Variant | None:
        tried = [v.text for (s, subject, body, _), v in self.cache.items() if v is not None and s == slot and (subject, body) == (champion.subject, champion.body)]
        feedback: list[str] = []
        for _ in range(self.settings.writer.max_attempts):
            text, cta, hypothesis = self.writer.write(slot, champion, lessons, tried, feedback)
            self.spend.calls += 1
            found = problems(slot, text, cta if slot == "body" else "", self.settings.fact_sheet, self.settings.writer, self.placeholders)
            if not found:
                return Variant(text, cta if slot == "body" else "", self._quality(slot, text, cta), placeholder=True, hypothesis=hypothesis)
            self.spend.rejected.append(f"{slot} “{text}”: {'; '.join(found)}")
            feedback = found
        return None  # every draft failed a check, so nothing is sent; the loop tries the other part

    def _rating(self, slot: str, text: str, cta: str) -> float:
        key = (slot, text, cta)
        if key not in self.ratings:
            self.ratings[key] = self.judge.rate(slot, text, cta)
            self.spend.calls += 1
        return self.ratings[key]

    def _quality(self, slot: str, text: str, cta: str) -> float:
        """The judge's rating against your first draft's, as hidden quality (100 = your first draft), with noise
        drawn from the words themselves so the same draft always gets the same quality."""
        rules = self.settings.writer
        noise = random.Random(zlib.crc32(f"{slot}\n{text}\n{cta}".encode())).gauss(0.0, rules.rating_noise)
        return 100 * math.exp(rules.quality_per_point * (self._rating(slot, text, cta) - self.reference[slot]) + noise)

    def summary(self) -> list[str]:
        return [
            f"Written by {self.writer.model}, judged by {self.judge.model}: {self.spend.calls:,} calls, ${self.spend.cost:,.2f} reported by OpenRouter.",
            *(f"- Rejected and rewritten: {r}" for r in self.spend.rejected),
        ]


def _post(url: str, payload: dict[str, Any], api_key: str) -> dict[str, Any]:
    request = urllib.request.Request(url, json.dumps(payload).encode(), {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body: dict[str, Any] = json.loads(response.read())
            return body
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"OpenRouter refused the call ({error.code}): {error.read().decode(errors='replace')[:300]}") from None


@dataclass
class OpenRouterWriter:
    """Writes with an LLM on OpenRouter's chat endpoint, asking for JSON."""

    model: str
    api_key: str
    facts: FactSheet
    spend: Spend
    post: Post = _post

    def write(self, slot: str, champion: Email, lessons: list[str], tried: list[str], feedback: list[str]) -> tuple[str, str, str]:
        rules = (
            "You write win-back emails for a Shopify app that lets merchants clone a store to start from. "
            "State only facts from this fact sheet, and no other numbers or prices:\n- " + "\n- ".join(self.facts.facts)
            + "\nNever use these phrases: " + ", ".join(self.facts.banned_phrases)
            + ". Never start a subject with Re: or Fwd:. Keep subjects under 60 characters. You may use {first_name} and {store_name}."
        )
        ask = (
            f"Reader: {IDLE_MERCHANT}\nCurrent best email (the champion):\nSubject: {champion.subject}\nBody: {champion.body}\nButton: {champion.cta}\n\n"
            f"Write a new {slot} that changes one thing about the champion's {slot}, and say what it changes and why (the hypothesis)."
            + ("\nWhat earlier tests found:\n- " + "\n- ".join(lessons) if lessons else "")
            + ("\nAlready tried, so write something different:\n- " + "\n- ".join(tried) if tried else "")
            + ("\nYour last draft was rejected because: " + "; ".join(feedback) if feedback else "")
        )
        schema = {
            "type": "object",
            "properties": {"text": {"type": "string"}, "button": {"type": "string"}, "hypothesis": {"type": "string"}},
            "required": ["text", "button", "hypothesis"],
            "additionalProperties": False,
        }
        reply = self.post(OPENROUTER, {
            "model": self.model,
            "messages": [{"role": "system", "content": rules}, {"role": "user", "content": ask + ("\nFor a subject, leave button empty." if slot == "subject" else "")}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "variant", "strict": True, "schema": schema}},
            "usage": {"include": True},
        }, self.api_key)
        self.spend.cost += float(reply.get("usage", {}).get("cost") or 0.0)
        try:
            answer = json.loads(reply["choices"][0]["message"]["content"])
            return str(answer["text"]).strip(), str(answer.get("button", "")).strip(), str(answer["hypothesis"]).strip()
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
            raise RuntimeError(f"The writer's answer wasn't the JSON asked for: {str(reply)[:300]}") from error


@dataclass
class JevJudge:
    """Rates appeal with a decision model on OpenRouter's Decisions API (alpha): one 1-10 score question."""

    model: str
    api_key: str
    spend: Spend
    post: Post = _post

    def rate(self, slot: str, text: str, cta: str) -> float:
        reply = self.post(DECISIONS, {
            "model": self.model,
            "state": {"reader": IDLE_MERCHANT, "email_part": slot, "words": text + (f"\nButton: {cta}" if cta else "")},
            "questions": {"appeal": {
                "type": "score",
                "instructions": f"How likely is the reader to {'open the email, from this subject' if slot == 'subject' else 'click the button, from this body'}?",
                "criteria": APPEAL_LEVELS,
            }},
        }, self.api_key)
        self.spend.cost += float(reply.get("usage", {}).get("cost") or 0.0)
        try:
            return 1.0 + float(reply["answers"]["appeal"]["score"])  # positions run from 0, ratings from 1
        except (KeyError, TypeError, ValueError) as error:
            raise RuntimeError(f"The judge's answer wasn't a score (the Decisions API is in alpha and may have changed): {str(reply)[:300]}") from error


def plumbing(settings: Settings, api_key: str, post: Post | None = None) -> list[str]:
    """One real write-and-judge round trip: a new Idle subject against your first draft, its checks and its rating."""
    copywriter = openrouter(settings, api_key, post)
    draft = settings.first_drafts["idle"]
    variant = copywriter.challenger("subject", Email(draft.subject, draft.body, draft.cta), [], 0)
    lines = [f"Your first draft's subject is rated {copywriter.reference['subject']:.1f} of 10 by {settings.writer.judge_model}."]
    if variant is None:
        lines.append("Every draft failed a check, so nothing would be sent:")
    else:
        lines += [f"{settings.writer.writer_model} wrote: {variant.text}", f"Hypothesis: {variant.hypothesis}",
                  f"Rated {copywriter.ratings[('subject', variant.text, '')]:.1f} of 10, so its hidden quality is {variant.quality:.0f} (yours is 100)."]
    lines += [f"Rejected: {r}" for r in copywriter.spend.rejected]
    return lines + [f"{copywriter.spend.calls} calls, ${copywriter.spend.cost:.4f}."]


def openrouter(settings: Settings, api_key: str, post: Post | None = None) -> AiCopywriter:
    """The real copywriter: DeepSeek writes, Jev judges (the models are in settings), with one key for both."""
    spend, rules, post = Spend(), settings.writer, post or _post
    return AiCopywriter(settings, OpenRouterWriter(rules.writer_model, api_key, settings.fact_sheet, spend, post), JevJudge(rules.judge_model, api_key, spend, post), spend)
