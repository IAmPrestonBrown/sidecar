"""Pydantic models and tool schemas for coach outputs."""

import logging
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ValidationError

log = logging.getLogger(__name__)

CardKind = Literal[
    "DIG_HERE",
    "COUNTEREVIDENCE",
    "GET_SPECIFIC",
    "TRACE_THIS",
    "NEW_PROBLEM",
    "LEADING",
    "ONE_QUESTION",
    "TALKING_TOO_MUCH",
    "KEEP_LISTENING",
    "REDIRECT",
    "WRAP_UP",
    "CHECK_SPEAKERS",
]
Tag = Literal["H1", "H2", "H3", "H4", "H5", "H6", "COUNTER", "NEW"]
HypothesisId = Literal["H1", "H2", "H3", "H4", "H5", "H6", "NEW"]
Stance = Literal["SUPPORTS", "CONTRADICTS", "MIXED", "NEW"]
Direction = Literal["SUPPORTS", "CONTRADICTS", "MIXED"]
EvidenceKind = Literal[
    "BEHAVIOR", "INCIDENT", "OPINION", "CAPABILITY_CLAIM", "ARTIFACT", "SEGMENT", "SECONDHAND"
]
MarkEvidenceType = Literal[
    "CONCRETE_BEHAVIOR",
    "PAST_INCIDENT",
    "OPINION",
    "HYPOTHETICAL",
    "SECONDHAND",
    "CAPABILITY_CLAIM",
]


def _word_cap(limit: int) -> BeforeValidator:
    def cap(value: Any) -> Any:
        if isinstance(value, str):
            words = value.split()
            if len(words) > limit:
                return " ".join(words[:limit]) + " ..."
            return value.strip()
        return value

    return BeforeValidator(cap)


def _list_cap(limit: int) -> BeforeValidator:
    def cap(value: Any) -> Any:
        if isinstance(value, list):
            return value[:limit]
        return value

    return BeforeValidator(cap)


def _dedupe(value: Any) -> Any:
    if isinstance(value, list):
        return list(dict.fromkeys(value))
    return value


Words8 = Annotated[str, _word_cap(8)]
Words12 = Annotated[str, _word_cap(12)]
Words15 = Annotated[str, _word_cap(15)]
Words20 = Annotated[str, _word_cap(20)]
TagList = Annotated[list[Tag], BeforeValidator(_dedupe)]


class Card(BaseModel):
    kind: CardKind
    headline: Words8
    ask: Words20 | None = None
    why: Words12
    tags: TagList = []
    quote: Words12 | None = None


class Evidence(BaseModel):
    at: str
    stance: Stance
    hypotheses: TagList = []
    type: EvidenceKind
    note: Words15
    quote: Words20


class CoachUpdate(BaseModel):
    intervene: bool
    cards: Annotated[list[Card], _list_cap(2)] = []
    evidence: Annotated[list[Evidence], _list_cap(3)] = []


class HypothesisEffect(BaseModel):
    id: HypothesisId
    direction: Direction


class MarkAnalysis(BaseModel):
    headline: Words8
    claim: Words20
    evidence_type: MarkEvidenceType
    hypotheses: list[HypothesisEffect] = []
    contradiction: Words20 | None = None
    unknown: Words20
    ask: Words20
    why: Words12


class AskNext(BaseModel):
    ask: Words20
    why: Words12
    tags: TagList = []


MODE_TOOLS: dict[str, tuple[str, type[BaseModel]]] = {
    "live": ("coach_update", CoachUpdate),
    "mark": ("mark_analysis", MarkAnalysis),
    "ask_next": ("ask_next", AskNext),
}


def validate_output(mode: str, data: Any) -> BaseModel | None:
    """Validate tool input for a mode. Return None if it is malformed."""
    _, model = MODE_TOOLS[mode]
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        log.warning("Discarding malformed %s output: %s", mode, exc.errors()[:3])
        return None


def _enum(values: Any) -> dict:
    return {"type": "string", "enum": list(values.__args__)}


def _nullable_str(description: str) -> dict:
    return {"type": ["string", "null"], "description": description}


def _str(description: str) -> dict:
    return {"type": "string", "description": description}


def _obj(properties: dict) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


_TAGS = {"type": "array", "items": _enum(Tag)}

_CARD = _obj(
    {
        "kind": _enum(CardKind),
        "headline": _str("At most 8 words."),
        "ask": _nullable_str("One spoken question, at most 20 words, or null."),
        "why": _str("At most 12 words."),
        "tags": _TAGS,
        "quote": _nullable_str("Triggering words copied from the transcript, at most 12 words."),
    }
)

_EVIDENCE = _obj(
    {
        "at": _str("Transcript time as mm:ss."),
        "stance": _enum(Stance),
        "hypotheses": _TAGS,
        "type": _enum(EvidenceKind),
        "note": _str("At most 15 words."),
        "quote": _str("Copied from the transcript, at most 20 words."),
    }
)

TOOLS: list[dict] = [
    {
        "name": "coach_update",
        "description": "Live coaching update. At most 2 cards and at most 3 new evidence items.",
        "strict": True,
        "eager_input_streaming": True,
        "input_schema": _obj(
            {
                "intervene": {"type": "boolean"},
                "cards": {"type": "array", "items": _CARD, "description": "At most 2."},
                "evidence": {"type": "array", "items": _EVIDENCE, "description": "At most 3."},
            }
        ),
    },
    {
        "name": "mark_analysis",
        "description": "Deeper analysis of the marked moment.",
        "strict": True,
        "eager_input_streaming": True,
        "input_schema": _obj(
            {
                "headline": _str("At most 8 words."),
                "claim": _str("What was actually claimed, at most 20 words."),
                "evidence_type": _enum(MarkEvidenceType),
                "hypotheses": {
                    "type": "array",
                    "items": _obj({"id": _enum(HypothesisId), "direction": _enum(Direction)}),
                },
                "contradiction": _nullable_str(
                    "Contradiction and its time, at most 20 words, or null."
                ),
                "unknown": _str("What remains unknown, at most 20 words."),
                "ask": _str("One spoken question, at most 20 words."),
                "why": _str("At most 12 words."),
            }
        ),
    },
    {
        "name": "ask_next",
        "description": "The single best next question.",
        "strict": True,
        "eager_input_streaming": True,
        "input_schema": _obj(
            {
                "ask": _str("One spoken question, at most 20 words."),
                "why": _str("At most 12 words."),
                "tags": _TAGS,
            }
        ),
    },
]
