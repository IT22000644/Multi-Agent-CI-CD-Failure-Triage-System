from __future__ import annotations

import json
from json import JSONDecodeError

from pydantic import BaseModel, ValidationError


class StructuredLLMOutputError(RuntimeError):
    """Raised when an LLM response cannot be parsed as the expected JSON model."""


def extract_json_object(text: str) -> dict[str, object]:
    decoder = json.JSONDecoder()
    stripped = text.strip()
    candidates = [stripped]

    if "```" in stripped:
        parts = stripped.split("```")
        candidates.extend(part.strip() for part in parts if part.strip())

    for candidate in candidates:
        if candidate.startswith("json"):
            candidate = candidate[4:].strip()

        start = candidate.find("{")
        if start == -1:
            continue

        try:
            parsed, _ = decoder.raw_decode(candidate[start:])
        except JSONDecodeError:
            continue

        if isinstance(parsed, dict):
            return parsed

    raise StructuredLLMOutputError("LLM response did not contain a valid JSON object.")


def parse_llm_json_output[OutputModel: BaseModel](
    text: str,
    model_type: type[OutputModel],
    *,
    context: str,
) -> OutputModel:
    try:
        return model_type.model_validate(extract_json_object(text))
    except ValidationError as exc:
        raise StructuredLLMOutputError(
            f"{context} LLM response did not match the expected schema: {exc}"
        ) from exc


__all__ = [
    "StructuredLLMOutputError",
    "extract_json_object",
    "parse_llm_json_output",
]
