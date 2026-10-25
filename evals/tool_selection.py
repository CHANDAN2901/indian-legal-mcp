"""Tool-selection eval: does the model pick the right MCP tool for each question?

Each question goes to the model together with every server's real tool definitions (the same names, descriptions
and input schemas an MCP client like Claude Desktop receives). The score is how often the model's first tool call
is one of the acceptable tools. An OpenAI model stands in for Claude.

    uv run --env-file .env python evals/tool_selection.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

import anyio
import httpx2

from indiankanoon_mcp.server import mcp as indiankanoon
from supabase_reader_mcp.server import mcp as supabase_reader
from tavily_web_mcp.server import mcp as tavily_web

SERVERS = [indiankanoon, supabase_reader, tavily_web]
NONE = "none"  # the model should answer directly, without calling a tool
TARGET = 0.9
HISTORY = Path(__file__).with_name("history.jsonl")

# (question, acceptable first tools). More than one is accepted where several first steps are reasonable,
# e.g. list_tables before query_table when the model hasn't seen the database schema yet.
CASES: list[tuple[str, set[str]]] = [
    # Case law -> indiankanoon
    ("Find Supreme Court judgments on triple talaq.", {"search_cases"}),
    ("Show me Delhi High Court cheque bounce cases from 2019.", {"search_cases"}),
    ("What precedents exist on misuse of Section 498A IPC?", {"search_cases"}),
    ("Find Indian court cases about employers monitoring employees' devices.", {"search_cases"}),
    ("Read the full judgment for case_id 91938676.", {"get_judgment"}),
    ("What was the court's final order in case 143202244?", {"get_judgment"}),
    ("Open this judgment and summarise the holding: https://indiankanoon.org/doc/168671544/", {"get_judgment"}),
    ("Which later cases have cited the judgment with case_id 91938676?", {"get_judgment", "search_cases"}),
    # Current events and web pages -> tavily-web
    ("What's the latest news on the DPDP Act rules?", {"search_web"}),
    ("What has LiveLaw reported this week about bail jurisprudence?", {"search_web"}),
    ("Who won yesterday's IPL match?", {"search_web"}),
    ("What is the current repo rate set by the RBI?", {"search_web"}),
    ("Find recent commentary on how the DPDP Act affects workplace surveillance.", {"search_web"}),
    ("Summarise this article: https://www.livelaw.in/top-stories/supreme-court-privacy-ruling-2026", {"fetch_url"}),
    ("Read https://docs.tavily.com/documentation/api-credits and tell me what an extract call costs.", {"fetch_url"}),
    # The user's own data -> supabase-reader
    ("What tables are in my database?", {"list_tables"}),
    ("Find anything in my database that mentions 'keystroke'.", {"search_records"}),
    ("Which client has the email priya.mehta@example.com?", {"search_records", "list_tables", "query_table"}),
    ("Show the 5 most recently opened legal matters.", {"list_tables", "query_table"}),
    ("List upcoming hearings that don't have an outcome yet.", {"list_tables", "query_table"}),
    ("List all my clients from Delhi.", {"list_tables", "query_table", "search_records"}),
    ("How many open matters does Farhan Qureshi have?", {"search_records", "list_tables", "query_table"}),
    # No tool needed
    ("What is 17 times 23?", {NONE}),
    ("Rewrite this more formally: the court said no to his plea.", {NONE}),
    ("Explain in simple words what a writ petition is.", {NONE}),
    # Harder: the tools overlap, or the obvious tool can't be called yet
    ("Get me the text of the Puttaswamy privacy judgment.", {"search_cases"}),  # no case_id known yet
    ("Find the Bombay High Court's 2024 judgments on workplace surveillance.", {"search_cases"}),
    ("Is there any news about courts applying Puttaswamy to private companies?", {"search_web"}),
    ("What does Section 7 of the Digital Personal Data Protection Act, 2023 say?", {"search_cases", "search_web"}),
    ("Look up Arjun Rao's matters in my records and the judgments they rely on.", {"search_records", "list_tables"}),
]


async def load_tools() -> tuple[list[dict], str]:
    """Every server's tools in OpenAI's function format, plus the servers' instructions for the system prompt."""
    tools, instructions = [], []
    for server in SERVERS:
        instructions.append(f"- {server.name}: {server.instructions}")
        for tool in await server.list_tools():
            tools.append(
                {
                    "type": "function",
                    "function": {"name": tool.name, "description": tool.description, "parameters": tool.input_schema},
                }
            )
    system = (
        f"You are a helpful assistant. Today is {date.today():%d %B %Y}. Use a tool only when it helps answer. "
        "Connected tool servers:\n" + "\n".join(instructions)
    )
    return tools, system


async def first_tool(http: httpx2.AsyncClient, model: str, system: str, tools: list[dict], question: str) -> str:
    response = await http.post(
        "/chat/completions",
        json={
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": question}],
            "tools": tools,
        },
    )
    response.raise_for_status()
    calls = response.json()["choices"][0]["message"].get("tool_calls") or []
    return calls[0]["function"]["name"] if calls else NONE


async def main() -> int:
    model = os.environ.get("OPENAI_MODEL", "gpt-5.4-mini")
    tools, system = await load_tools()
    misses = []
    async with httpx2.AsyncClient(
        base_url="https://api.openai.com/v1",
        headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
        timeout=120,
    ) as http:
        for question, expected in CASES:
            got = await first_tool(http, model, system, tools, question)
            ok = got in expected
            if not ok:
                misses.append({"question": question, "got": got, "expected": sorted(expected)})
            hint = "" if ok else f"  [expected {'/'.join(sorted(expected))}]"
            print(f"{'✓' if ok else '✗'} {got:<15} {question}{hint}")

    score = 1 - len(misses) / len(CASES)
    print(f"\n{model}: {len(CASES) - len(misses)}/{len(CASES)} correct = {score:.0%} (target {TARGET:.0%})")
    with HISTORY.open("a") as f:
        f.write(
            json.dumps({"at": f"{datetime.now():%Y-%m-%d %H:%M}", "model": model, "score": score, "misses": misses})
            + "\n"
        )
    return 0 if score >= TARGET else 1


if __name__ == "__main__":
    sys.exit(anyio.run(main))
