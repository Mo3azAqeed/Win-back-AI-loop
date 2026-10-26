"""Where the AI loop's new subjects and bodies come from: the stand-in writer's prewritten list, or the real
writer and judge on OpenRouter (#13).

The loop asks a copywriter for the next challenger part: given the champion it will be tested against, the
playbook's conclusions so far and which part to change, the copywriter returns a variant with
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
import sys
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

    def challenger(self, slot: str, champion: Email, conclusions: list[str], nth: int) -> Variant | None:
        """The nth new part for this slot ("subject" or "body") in this replay, written against this champion."""
        ...

    def start_replay(self) -> None:
        """A new replay begins, so the copywriter can say how many replays made live calls."""
        ...

    def summary(self) -> list[str]:
        """What the report says about who wrote and judged, and what it cost; nothing for the stand-in writer."""
        ...


@dataclass
class StandIn:
    """The stand-in writer: the prewritten subjects and bodies, in order, with their placeholder qualities."""

    settings: Settings
    name: str = STAND_IN

    def challenger(self, slot: str, champion: Email, conclusions: list[str], nth: int) -> Variant | None:
        waiting = self.settings.prewritten_subjects if slot == "subject" else self.settings.prewritten_bodies
        return waiting[nth] if nth < len(waiting) else None

    def start_replay(self) -> None:
        pass

    def summary(self) -> list[str]:
        return []


# Numbers written as words: a draft can't state one, since the fact sheet gives every number in figures.
NUMBER_WORDS = re.compile(r"\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|twenty|thirty|forty|fifty|hundred|thousand|million|half|double|twice|dozen)\b", re.I)
# A figure with what makes it a claim: a price, a percentage, a duration or a count of something.
FIGURE = re.compile(r"\$?\d+(?:[.,]\d+)?(?:[\s-]*(?:%|/\s*month|percent|days?|hours?|minutes?|weeks?|months?)\b|%)?", re.I)


def _figure(text: str) -> str:
    """A figure in one written form: "7-day", "7 days" and "7 Days" are the same figure."""
    return re.sub(r"[\s-]+", "", text.lower()).removesuffix("s")


def problems(slot: str, text: str, cta: str, facts: FactSheet, writer: WriterSettings, placeholders: set[str]) -> list[str]:
    """Why a draft can't be sent, if it can't: a figure that isn't on the fact sheet as written there (a price,
    percentage or number), a number in words, a banned phrase, a subject posing as a reply or forward or too
    long, a placeholder the app can't fill, or a body without a button."""
    words, found = re.sub(r"\{[a-z_]+\}", "", f"{text} {cta}"), []
    sheet = " ".join(facts.facts).lower()
    on_sheet = {_figure(f) for f in FIGURE.findall(sheet)}  # whole figures only: "$4" is not "$40/month"
    for figure in FIGURE.findall(words):
        if _figure(figure) not in on_sheet:
            found.append(f'"{figure.strip()}" is not on the fact sheet')
    for word in NUMBER_WORDS.findall(words):
        if not re.search(rf"\b{word.lower()}\b", sheet):  # "one plan" is on the sheet; "nine out of ten" is not
            found.append(f'"{word}" states a number in words that isn\'t on the fact sheet')
    for phrase in facts.banned_phrases:
        if phrase.lower() in words.lower():
            found.append(f'it contains the banned phrase "{phrase}"')
    if slot == "subject" and re.match(r"\s*(re|fwd?)\s*:", text, re.I):
        found.append("the subject pretends to be a reply or a forward")
    if slot == "subject" and len(text) > writer.subject_max_characters:
        found.append(f"the subject is longer than {writer.subject_max_characters} characters")
    if slot == "body" and not cta.strip():
        found.append("the body has no button text")
    for name in set(re.findall(r"\{[a-z_]+\}", f"{text} {cta}")) - placeholders:
        found.append(f"{name} is not a placeholder the app can fill")
    if not text.strip():
        found.append("it is empty")
    return found


class Writer(Protocol):
    @property
    def model(self) -> str: ...

    def write(self, slot: str, champion: Email, conclusions: list[str], tried: list[str], feedback: list[str]) -> tuple[str, str, str]:
        """A new subject (cta empty) or body with its button, and its hypothesis."""
        ...


class Judge(Protocol):
    @property
    def model(self) -> str: ...

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

    def __init__(self, settings: Settings, writer: Writer, judge: Judge, spend: Spend | None = None, seed: int = 0,
                 warn: Callable[[str], None] = lambda message: print(message, file=sys.stderr)) -> None:
        if writer.model == judge.model:
            raise ValueError(f"The writer and the judge must be different models, not both {writer.model}")
        self.settings, self.writer, self.judge, self.seed = settings, writer, judge, seed
        self.name = f"AI writer ({writer.model})"
        self.spend = spend or Spend()  # shared with the writer and the judge, which add what each call cost
        # The nth new part of each kind is written once per run, against the champion of the first replay that
        # asks for it, and every replay reuses it: a run makes at most this many write-and-judge rounds whatever
        # its number of replays. A part changes one thing, so it still fits a later champion's other part.
        self.cache: dict[tuple[str, int], Variant | None] = {}
        self.ratings: dict[tuple[str, str, str], float] = {}
        # The spending cap (#14): a warning once spend passes one limit, no live call once it reaches the other.
        self.warn = warn
        self.warning: str | None = None  # what was said when spend passed the warning limit
        self.skipped = 0  # challengers not written, or not judged, because spend had reached the stop limit
        self.replay_calls: list[int] = []  # calls made in each replay so far, the last one still running
        draft = settings.first_drafts["idle"]
        self.placeholders = {p for e in settings.first_drafts.values() for p in re.findall(r"\{[a-z_]+\}", f"{e.subject} {e.body} {e.cta}")}
        self.reference = {"subject": self._rating("subject", draft.subject, ""), "body": self._rating("body", draft.body, draft.cta)}

    def challenger(self, slot: str, champion: Email, conclusions: list[str], nth: int) -> Variant | None:
        key = (slot, nth)
        if nth >= self.settings.writer.challengers_per_part:
            return None
        if key not in self.cache:
            self.cache[key] = self._write(slot, champion, conclusions, nth)
        return self.cache[key]

    def _write(self, slot: str, champion: Email, conclusions: list[str], nth: int) -> Variant | None:
        tried = [v.text for (s, _), v in self.cache.items() if v is not None and s == slot]
        feedback: list[str] = []
        for _ in range(self.settings.writer.max_attempts):
            if self.stopped:
                self.skipped += 1
                return None  # past the cap: no live call, so the loop keeps the variants already written and judged
            text, cta, hypothesis = self.writer.write(slot, champion, conclusions, tried, feedback)
            self._record_call()
            found = problems(slot, text, cta if slot == "body" else "", self.settings.fact_sheet, self.settings.writer, self.placeholders)
            if not found:
                if self.stopped and (slot, text, cta) not in self.ratings:
                    self.skipped += 1
                    return None  # written, but the cap leaves no call to judge it, and an unjudged draft is never sent
                return Variant(text, cta if slot == "body" else "", self._quality(slot, text, cta), placeholder=True, hypothesis=hypothesis)
            self.spend.rejected.append(f"{slot} “{text}”: {'; '.join(found)}")
            feedback = found
        return None  # every draft failed a check, so nothing is sent; the loop tries the other part

    def _rating(self, slot: str, text: str, cta: str) -> float:
        key = (slot, text, cta)
        if key not in self.ratings:
            self.ratings[key] = self.judge.rate(slot, text, cta)
            self._record_call()
        return self.ratings[key]

    @property
    def stopped(self) -> bool:
        return self.spend.cost >= self.settings.writer.spend_stop

    def _record_call(self) -> None:
        self.spend.calls += 1
        if self.replay_calls:
            self.replay_calls[-1] += 1
        limit = self.settings.writer.spend_warning
        if self.warning is None and self.spend.cost > limit:
            self.warning = f"Spend passed the ${limit:,.2f} warning limit (${self.spend.cost:,.2f} so far); the run keeps going."
            self.warn(self.warning)

    def start_replay(self) -> None:
        self.replay_calls.append(0)

    def _quality(self, slot: str, text: str, cta: str) -> float:
        """The judge's rating against your first draft's, as hidden quality (100 = your first draft), with noise
        drawn from the run's seed and the words, so every replay of a run agrees on a draft and runs differ."""
        rules = self.settings.writer
        noise = random.Random(zlib.crc32(f"{self.seed}\n{slot}\n{text}\n{cta}".encode())).gauss(0.0, rules.rating_noise)
        return 100 * math.exp(rules.quality_per_point * (self._rating(slot, text, cta) - self.reference[slot]) + noise)

    def summary(self) -> list[str]:
        rules, live = self.settings.writer, sum(1 for calls in self.replay_calls if calls)
        return [
            f"Written by {self.writer.model}, judged by {self.judge.model}: {self.spend.calls:,} calls, ${self.spend.cost:,.2f} reported by OpenRouter"
            f" (warn at ${rules.spend_warning:,.2f}, stop at ${rules.spend_stop:,.2f}).",
            "",
            f"- {live} of {len(self.replay_calls)} replays made live calls; {len(self.replay_calls) - live} reused variants already written and judged in this run.",
            *([f"- {self.warning}"] if self.warning else []),
            *([f"- Spend reached the ${rules.spend_stop:,.2f} stop: no live calls after that (the call that crossed it was already made). "
               f"{self.skipped} challenger{'s' if self.skipped != 1 else ''} went unwritten, so the loop tested fewer; every replay finished on the variants already written and judged."]
              if self.stopped else []),
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
    except (urllib.error.URLError, TimeoutError) as error:
        raise RuntimeError(f"Couldn't reach OpenRouter at {url}: {error}") from None
    except json.JSONDecodeError:
        raise RuntimeError(f"OpenRouter's answer from {url} wasn't JSON (the Decisions API is in alpha and may have changed)") from None


@dataclass(frozen=True)
class OpenRouterWriter:
    """Writes with an LLM on OpenRouter's chat endpoint, asking for JSON."""

    model: str
    api_key: str = field(repr=False)
    settings: Settings = field(repr=False)
    spend: Spend = field(default_factory=Spend)
    post: Post = _post

    def write(self, slot: str, champion: Email, conclusions: list[str], tried: list[str], feedback: list[str]) -> tuple[str, str, str]:
        facts, drafts = self.settings.fact_sheet, self.settings.first_drafts
        placeholders = sorted({p for e in drafts.values() for p in re.findall(r"\{[a-z_]+\}", f"{e.subject} {e.body}")})
        rules = (
            "You write win-back emails for a Shopify app that lets merchants clone a store to start from. "
            "State only facts from this fact sheet, with numbers and prices exactly as written there, never any other:\n- " + "\n- ".join(facts.facts)
            + "\nNever use these phrases: " + ", ".join(facts.banned_phrases)
            + f". Never start a subject with Re: or Fwd:. Keep subjects under {self.settings.writer.subject_max_characters} characters. "
            + "You may use these placeholders and no others: " + ", ".join(placeholders) + ". Offers (more trial days, a discount) are only for Trialists: never mention them here."
            + "\nThe founder's own emails, for tone:\n" + "\n".join(f"- {stage}: {e.subject} / {e.body} [{e.cta}]" for stage, e in drafts.items())
        )
        ask = (
            f"Reader: {IDLE_MERCHANT}\nCurrent best email (the champion):\nSubject: {champion.subject}\nBody: {champion.body}\nButton: {champion.cta}\n\n"
            f"Write a new {slot} that changes one thing about the champion's {slot}, and say what it changes and why (the hypothesis)."
            + ("\nWhat earlier tests found:\n- " + "\n- ".join(conclusions) if conclusions else "")
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


@dataclass(frozen=True)
class JevJudge:
    """Rates appeal with a decision model on OpenRouter's Decisions API (alpha): one 1-10 score question."""

    model: str
    api_key: str = field(repr=False)
    spend: Spend = field(default_factory=Spend)
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
            position = float(reply["answers"]["appeal"]["score"])  # the levels' positions, from 0 (the API's legend) to 9
        except (KeyError, TypeError, ValueError) as error:
            raise RuntimeError(f"The judge's answer wasn't a score (the Decisions API is in alpha and may have changed): {str(reply)[:300]}") from error
        if not 0 <= position <= len(APPEAL_LEVELS) - 1:
            raise RuntimeError(f"The judge's score {position} is outside the 1-10 scale's positions (the Decisions API is in alpha and may have changed)")
        return 1.0 + position


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


def openrouter(settings: Settings, api_key: str, post: Post | None = None, seed: int = 0) -> AiCopywriter:
    """The real copywriter: the writer and judge models named in settings, on OpenRouter, with one key for both."""
    spend, rules, post = Spend(), settings.writer, post or _post
    writer = OpenRouterWriter(rules.writer_model, api_key, settings, spend, post)
    return AiCopywriter(settings, writer, JevJudge(rules.judge_model, api_key, spend, post), spend, seed)
