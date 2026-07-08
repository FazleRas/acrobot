"""Error-path coverage — both gaps flagged by the bot's own review of PR #2."""

import json

import pytest
from google.genai import errors as genai_errors

import acrobot.__main__ as entry
from acrobot.llm.gemini_provider import GeminiProvider
from acrobot.llm.provider import ProviderAuthError, ProviderError

PATCH = (
    "@@ -1,2 +1,3 @@\n"
    " def f():\n"
    "+    x = 1\n"
    "     return None\n"
)


class _AuthFailProvider:
    def generate(self, **kwargs):  # noqa: ANN003
        raise ProviderAuthError("bad key")


class TestMainAuthHandling:
    """main() must exit 1 with a clear stderr line on bad credentials."""

    def test_auth_error_exits_1_and_prints_to_stderr(self, monkeypatch, tmp_path, capsys):
        event = tmp_path / "event.json"
        event.write_text(
            json.dumps({"pull_request": {"number": 7, "draft": False, "head": {"sha": "abc"}}})
        )
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
        monkeypatch.setenv("GITHUB_TOKEN", "test-token")
        monkeypatch.setattr(entry, "GeminiProvider", _AuthFailProvider)
        monkeypatch.setattr(
            entry,
            "fetch_changed_files",
            lambda gh, n: [{"filename": "a.py", "status": "modified", "patch": PATCH}],
        )

        assert entry.main() == 1
        captured = capsys.readouterr()
        assert "bad key" in captured.err


def _provider_raising(exc: Exception) -> GeminiProvider:
    """Build an adapter whose client raises `exc` without needing real credentials."""
    provider = GeminiProvider.__new__(GeminiProvider)

    class _Models:
        def generate_content(self, **kwargs):  # noqa: ANN003
            raise exc

    class _Client:
        models = _Models()

    provider._client = _Client()  # type: ignore[assignment]
    return provider


def _api_error(code: int, message: str) -> genai_errors.APIError:
    return genai_errors.APIError(code, {"error": {"message": message, "code": code}})


class TestGeminiErrorMapping:
    """Adapter must map auth failures to ProviderAuthError, the rest to ProviderError."""

    @pytest.mark.parametrize(
        "exc",
        [
            _api_error(400, "API key not valid. Please pass a valid API key."),
            _api_error(401, "Request had invalid authentication credentials."),
            _api_error(403, "Permission denied."),
        ],
    )
    def test_auth_failures_raise_provider_auth_error(self, exc):
        from acrobot.schemas import FindingList

        provider = _provider_raising(exc)
        with pytest.raises(ProviderAuthError):
            provider.generate(model="m", system="s", prompt="p", schema=FindingList)

    @pytest.mark.parametrize(
        "exc",
        [
            _api_error(429, "Resource has been exhausted."),
            _api_error(500, "Internal error."),
            _api_error(503, "The service is currently unavailable."),
        ],
    )
    def test_other_api_errors_raise_provider_error_not_auth(self, exc):
        from acrobot.schemas import FindingList

        provider = _provider_raising(exc)
        with pytest.raises(ProviderError):
            provider.generate(model="m", system="s", prompt="p", schema=FindingList)
