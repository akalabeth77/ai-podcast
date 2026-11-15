"""Testy záložného reťazca LLM poskytovateľov (bez reálnych API volaní)."""

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import httpx
from openai import APIStatusError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ai_podcast_generator as gen  # noqa: E402

LONG_SCRIPT = "NAZOV: Ep. 99: Test\n\n" + " ".join(["slovo"] * 2500)


def status_error(code: int, body: str = '{"error":"x"}') -> APIStatusError:
    req = httpx.Request("POST", "https://example.test/chat/completions")
    resp = httpx.Response(code, request=req, text=body)
    return APIStatusError(f"Error code: {code}", response=resp, body=None)


def completion(text: str):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


PROVIDERS = [
    {"name": "Gemini", "base_url": "https://g.test", "api_key": "k1",
     "models": ["gemini-2.5-flash", "gemini-2.5-flash-lite"]},
    {"name": "OpenRouter", "base_url": "https://o.test", "api_key": "k2",
     "models": ["free-model"]},
]


class FakeOpenAI:
    """Vracia/vyhadzuje vopred pripravené výsledky podľa (base_url, model)."""
    script: dict = {}
    calls: list = []

    def __init__(self, api_key, base_url, **kw):
        self.base_url = base_url
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, model, **kw):
        FakeOpenAI.calls.append(model)
        outcome = FakeOpenAI.script[model]
        if isinstance(outcome, list):
            outcome = outcome.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return completion(outcome)


class CallLLMTests(unittest.TestCase):
    def setUp(self):
        FakeOpenAI.calls = []
        self.patch = mock.patch.object(gen, "OpenAI", FakeOpenAI)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.validate = lambda t: gen.parse_script_output(t, 99)

    def run_llm(self):
        return gen.call_llm("prompt", validate=self.validate,
                            providers=PROVIDERS, retry_delays=(0,))

    def test_402_on_gemini_falls_back_to_next_model(self):
        FakeOpenAI.script = {
            "gemini-2.5-flash": status_error(402),
            "gemini-2.5-flash-lite": LONG_SCRIPT,
        }
        text, used = self.run_llm()
        self.assertEqual(used, "Gemini/gemini-2.5-flash-lite")
        self.assertEqual(FakeOpenAI.calls, ["gemini-2.5-flash", "gemini-2.5-flash-lite"])

    def test_all_gemini_402_falls_back_to_openrouter(self):
        FakeOpenAI.script = {
            "gemini-2.5-flash": status_error(402),
            "gemini-2.5-flash-lite": status_error(402),
            "free-model": LONG_SCRIPT,
        }
        _, used = self.run_llm()
        self.assertEqual(used, "OpenRouter/free-model")

    def test_429_is_retried_on_same_model(self):
        FakeOpenAI.script = {"gemini-2.5-flash": [status_error(429), LONG_SCRIPT]}
        _, used = self.run_llm()
        self.assertEqual(used, "Gemini/gemini-2.5-flash")
        self.assertEqual(FakeOpenAI.calls, ["gemini-2.5-flash", "gemini-2.5-flash"])

    def test_402_is_not_retried(self):
        FakeOpenAI.script = {
            "gemini-2.5-flash": status_error(402),
            "gemini-2.5-flash-lite": LONG_SCRIPT,
        }
        self.run_llm()
        self.assertEqual(FakeOpenAI.calls.count("gemini-2.5-flash"), 1)

    def test_short_script_tries_next_model(self):
        FakeOpenAI.script = {
            "gemini-2.5-flash": "NAZOV: Ep. 99: Krátke\n\nkrátky text",
            "gemini-2.5-flash-lite": LONG_SCRIPT,
        }
        _, used = self.run_llm()
        self.assertEqual(used, "Gemini/gemini-2.5-flash-lite")

    def test_all_fail_raises_with_every_error(self):
        FakeOpenAI.script = {
            "gemini-2.5-flash": status_error(402, "credits depleted"),
            "gemini-2.5-flash-lite": status_error(404),
            "free-model": [status_error(503), status_error(503)],
        }
        with self.assertRaises(gen.LLMError) as ctx:
            self.run_llm()
        msg = str(ctx.exception)
        self.assertIn("HTTP 402 credits depleted", msg)
        self.assertIn("HTTP 404", msg)
        self.assertIn("OpenRouter/free-model", msg)

    def test_no_keys_raises(self):
        with self.assertRaises(EnvironmentError):
            gen.call_llm("p", providers=[])


class ProvidersTests(unittest.TestCase):
    def test_only_configured_providers_are_used(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "g"}, clear=True):
            names = [p["name"] for p in gen.get_llm_providers()]
        self.assertEqual(names, ["Gemini"])

    def test_openrouter_models_env_override_skips_discovery(self):
        env = {"OPENROUTER_API_KEY": "o", "OPENROUTER_MODELS": "a:free, b:free"}
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(gen, "discover_openrouter_free_models") as disc:
            provs = gen.get_llm_providers()
        disc.assert_not_called()
        self.assertEqual(provs[0]["models"], ["a:free", "b:free"])

    def test_discovery_filters_and_ranks_free_models(self):
        data = {"data": [
            {"id": "paid/model", "context_length": 128000},
            {"id": "tiny/model:free", "context_length": 8000},
            {"id": "other/thing:free", "context_length": 64000},
            {"id": "google/gemma-x:free", "context_length": 64000},
            {"id": "liquid/lfm-3-1.7b:free", "context_length": 64000},
            {"id": "cohere/north-mini-code:free", "context_length": 64000},
            {"id": "short/out:free", "context_length": 64000,
             "top_provider": {"max_completion_tokens": 8192}},
        ]}
        resp = mock.Mock(json=lambda: data, raise_for_status=lambda: None)
        with mock.patch.object(gen.httpx, "get", return_value=resp):
            self.assertEqual(gen.discover_openrouter_free_models(),
                             ["google/gemma-x:free", "other/thing:free"])

    def test_discovery_failure_returns_empty(self):
        with mock.patch.object(gen.httpx, "get", side_effect=httpx.ConnectError("down")):
            self.assertEqual(gen.discover_openrouter_free_models(), [])


class ParseTests(unittest.TestCase):
    def test_title_number_comes_from_code(self):
        title, script = gen.parse_script_output(
            "NAZOV: Ep. 3: Brusel reguluje\n\n" + " ".join(["a"] * 2100), 42)
        self.assertEqual(title, "Ep. 42: Brusel reguluje")
        self.assertFalse(script.startswith("NAZOV"))


if __name__ == "__main__":
    unittest.main()
