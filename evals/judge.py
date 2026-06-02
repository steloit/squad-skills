"""LLM-as-judge resolution for the GEval rubric — keyless-first.

Order of preference (the first that's available wins):
  1. ANTHROPIC_API_KEY      → AnthropicModel (CI path)
  2. DEEPEVAL_OLLAMA_MODEL   → local Ollama (fully offline, keyless)
  3. `claude` CLI login      → wrap `claude -p` (keyless, subscription)
  4. none                    → caller skips the rubric (board-state still gates)

Everything stays local: scores are captured via ``metric.measure()`` and never pushed
to a cloud dashboard.
"""
from __future__ import annotations

import os
import shutil

import runner


def resolve_judge():
    """Return (model, name) or (None, None) if no judge is available."""
    try:
        if os.environ.get("ANTHROPIC_API_KEY"):
            from deepeval.models import AnthropicModel
            m = AnthropicModel(model="claude-sonnet-4-6")
            return m, "anthropic:claude-sonnet-4-6"
    except Exception:
        pass
    try:
        ollama = os.environ.get("DEEPEVAL_OLLAMA_MODEL")
        if ollama:
            from deepeval.models import OllamaModel
            return OllamaModel(model=ollama), f"ollama:{ollama}"
    except Exception:
        pass
    try:
        if shutil.which("claude"):
            return _claude_cli_judge(), "claude-code-cli (login)"
    except Exception:
        pass
    return None, None


def _claude_cli_judge():
    """Keyless GEval judge backed by the Claude Code CLI login (best-effort)."""
    import json
    import re

    from deepeval.models.base_model import DeepEvalBaseLLM

    class ClaudeCliJudge(DeepEvalBaseLLM):
        def load_model(self):
            return self

        def get_model_name(self):
            return "claude-code-cli (login)"

        def generate(self, prompt: str, schema=None):
            if schema is None:
                return runner.claude_text(prompt)
            ask = (prompt + "\n\nReturn ONLY a JSON object (no prose, no code fence) "
                   "matching this schema:\n" + json.dumps(schema.model_json_schema()))
            text = runner.claude_text(ask)
            match = re.search(r"\{.*\}", text, re.S)
            return schema.model_validate_json(match.group(0)) if match else schema()

        async def a_generate(self, prompt: str, schema=None):
            return self.generate(prompt, schema)

    return ClaudeCliJudge()
