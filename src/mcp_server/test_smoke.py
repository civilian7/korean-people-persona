"""
스모크 테스트: MCP 서버의 tool 함수들을 직접 호출하고
stdio 서버 핸드셰이크가 가능한지 확인.

사용:
    PYTHONPATH=src python -m mcp_server.test_smoke
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

from . import tools


def hr(title: str) -> None:
    print(f"\n=== {title} ===")


def show(obj, max_chars: int = 800) -> None:
    s = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    if len(s) > max_chars:
        s = s[:max_chars] + "\n... (truncated)"
    print(s)


def test_direct() -> None:
    hr("stats")
    show(tools.stats(), max_chars=600)

    hr("search: 등산* AND 낚시*  (남자 60-79)")
    res = tools.search_persona(
        query="등산* AND 낚시*",
        filters={"sex": "남자", "age_min": 60, "age_max": 79},
        limit=3,
    )
    show(res)

    hr("search: 용접*  (skills_and_expertise만)")
    res = tools.search_persona(
        query="용접*",
        fields=["skills_and_expertise"],
        limit=3,
    )
    show(res)

    hr("sample_persona: 서울 여자 1인가구 5명")
    res = tools.sample_persona(
        filters={"province": "서울", "sex": "여자", "family_type_like": "%1인%"},
        n=3,
    )
    show(res)

    hr("aggregate: province × sex (60+)")
    res = tools.aggregate(
        group_by=["province", "sex"],
        filters={"age_min": 60},
        limit=10,
    )
    show(res)

    hr("get_persona: 첫 번째 결과 uuid")
    if res["groups"]:
        # search 결과에서 uuid 하나 가져와서
        s = tools.search_persona(query=None, filters={"sex": "여자"}, limit=1)
        if s["results"]:
            u = s["results"][0]["uuid"]
            show(tools.get_persona(u), max_chars=500)


async def test_stdio() -> None:
    """MCP stdio 서버를 실제로 띄워 list_tools / call_tool 호출."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    src_dir = str(Path(__file__).resolve().parents[1])
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_server"],
        env={"PYTHONPATH": src_dir, "PYTHONIOENCODING": "utf-8"},
    )

    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()

            hr("MCP list_tools")
            t = await session.list_tools()
            for tool in t.tools:
                print(f"  - {tool.name}: {(tool.description or '').splitlines()[0][:80]}")

            hr("MCP call_tool: stats")
            r2 = await session.call_tool("stats", {})
            for c in r2.content:
                if hasattr(c, "text"):
                    print(c.text[:500])

            hr("MCP call_tool: search_persona (등산*)")
            r3 = await session.call_tool(
                "search_persona",
                {"query": "등산*", "limit": 2},
            )
            for c in r3.content:
                if hasattr(c, "text"):
                    print(c.text[:800])


def main() -> int:
    try:
        test_direct()
    except Exception as e:
        print(f"[FAIL direct] {e!r}")
        return 1

    try:
        asyncio.run(test_stdio())
    except Exception as e:
        print(f"[FAIL stdio] {e!r}")
        return 1

    print("\n[OK] all smoke tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
