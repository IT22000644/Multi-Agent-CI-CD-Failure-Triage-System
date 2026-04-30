from __future__ import annotations

import pytest
from pydantic import BaseModel, Field

from src.llm import StructuredLLMOutputError, extract_json_object, parse_llm_json_output


class SampleOutput(BaseModel):
    summary: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)


def test_extract_json_object_from_plain_json() -> None:
    assert extract_json_object('{"summary": "ok"}') == {"summary": "ok"}


def test_extract_json_object_from_fenced_json() -> None:
    payload = extract_json_object(
        """```json
        {"summary": "ok", "tags": ["ci"]}
        ```"""
    )

    assert payload == {"summary": "ok", "tags": ["ci"]}


def test_parse_llm_json_output_validates_model() -> None:
    parsed = parse_llm_json_output(
        '{"summary": "ok", "tags": ["ci"]}',
        SampleOutput,
        context="Sample",
    )

    assert parsed.summary == "ok"
    assert parsed.tags == ["ci"]


def test_parse_llm_json_output_raises_for_malformed_json() -> None:
    with pytest.raises(StructuredLLMOutputError):
        parse_llm_json_output("not json", SampleOutput, context="Sample")


def test_parse_llm_json_output_raises_for_missing_fields() -> None:
    with pytest.raises(StructuredLLMOutputError):
        parse_llm_json_output('{"tags": ["ci"]}', SampleOutput, context="Sample")
