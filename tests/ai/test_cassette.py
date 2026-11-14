"""F07 cassettes: record once, replay for free. Spec: docs/features/F07-llm-layer.md."""

import json
from pathlib import Path

import pytest

from quarantix.ai.cassette import CassetteLLM, cassette_key
from quarantix.ai.llm import CassetteMiss, Message, ToolCall, ToolDef
from tests.ai._fakes import ScriptedLLM

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
TOOLS = [
    ToolDef(
        "lookup", "Look something up.", {"type": "object", "properties": {"q": {"type": "string"}}}
    )
]


async def _ask(llm: CassetteLLM, user: str = "hello") -> object:
    return (await llm.json(model="m-1", system="sys", user=user, schema=SCHEMA)).value


async def test_record_then_replay_gives_identical_results_without_calling_the_model(
    tmp_path: Path,
) -> None:
    inner = ScriptedLLM(json_value={"ok": True})
    assert await _ask(CassetteLLM(inner, tmp_path, "record")) == {"ok": True}
    assert inner.json_calls == 1

    offline = CassetteLLM(None, tmp_path, "replay")  # no model at all
    assert await _ask(offline) == {"ok": True}


async def test_a_replay_miss_raises(tmp_path: Path) -> None:
    with pytest.raises(CassetteMiss):
        await _ask(CassetteLLM(None, tmp_path, "replay"), "never recorded")


async def test_live_mode_never_writes_cassettes(tmp_path: Path) -> None:
    await _ask(CassetteLLM(ScriptedLLM(), tmp_path, "live"))
    assert list(tmp_path.rglob("*.json")) == []


async def test_record_mode_reuses_an_existing_recording(tmp_path: Path) -> None:
    inner = ScriptedLLM()
    llm = CassetteLLM(inner, tmp_path, "record")
    await _ask(llm)
    await _ask(llm)
    assert inner.json_calls == 1  # the second identical request is a cassette hit


async def test_identical_first_turns_are_recorded_once(tmp_path: Path) -> None:
    inner = ScriptedLLM(
        turn=Message(role="assistant", tool_calls=(ToolCall("c1", "lookup", {"q": "x"}),))
    )
    llm = CassetteLLM(inner, tmp_path, "record")
    first = [Message(role="user", text="Process today's queue.")]
    one = await llm.tool_turn(model="m-1", system="sys", messages=first, tools=TOOLS)
    two = await llm.tool_turn(model="m-1", system="sys", messages=first, tools=TOOLS)
    assert inner.turn_calls == 1
    assert one.message == two.message
    assert two.message.tool_calls[0].arguments == {"q": "x"}


def test_keys_do_not_depend_on_dict_order() -> None:
    a = cassette_key("json", "m", {"system": "s", "user": "u", "schema": {"b": 1, "a": 2}})
    b = cassette_key("json", "m", {"schema": {"a": 2, "b": 1}, "user": "u", "system": "s"})
    assert a == b
    assert a != cassette_key(
        "json", "m", {"system": "s", "user": "other", "schema": {"a": 2, "b": 1}}
    )


async def test_a_corrupted_cassette_is_a_miss_in_replay_and_re_recorded_in_record_mode(
    tmp_path: Path,
) -> None:
    inner = ScriptedLLM()
    await _ask(CassetteLLM(inner, tmp_path, "record"))
    (path,) = tmp_path.rglob("*.json")
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(CassetteMiss):
        await _ask(CassetteLLM(None, tmp_path, "replay"))
    await _ask(CassetteLLM(inner, tmp_path, "record"))
    assert inner.json_calls == 2
    assert json.loads(path.read_text(encoding="utf-8"))["reply"]["value"] == {"ok": True}


def test_cassettes_are_sharded_by_key_prefix(tmp_path: Path) -> None:
    key = cassette_key("json", "m", {"x": 1})
    path = CassetteLLM(None, tmp_path, "replay").path_for(key)
    assert path == tmp_path / key[:2] / f"{key}.json"


def test_committed_cassettes_contain_no_secrets() -> None:
    from quarantix.core.redact import scrub

    root = Path(__file__).resolve().parents[2] / "cassettes"
    leaks = [p.name for p in root.rglob("*.json") if scrub(p.read_text(encoding="utf-8"))[1]]
    assert leaks == []
