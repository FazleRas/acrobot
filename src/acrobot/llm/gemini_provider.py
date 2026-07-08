"""Gemini adapter (google-genai SDK) for the Provider protocol."""

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel

from acrobot.llm.provider import ProviderAuthError, ProviderError, ProviderResponse, Usage


class GeminiProvider:
    def __init__(self, api_key: str | None = None) -> None:
        # Falls back to the GEMINI_API_KEY env var when api_key is None.
        self._client = genai.Client(api_key=api_key) if api_key else genai.Client()

    def generate(
        self,
        *,
        model: str,
        system: str,
        prompt: str,
        schema: type[BaseModel],
        reasoning: bool = False,
    ) -> ProviderResponse:
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=schema,
            # Protocol `reasoning` → Gemini thinking budget: -1 dynamic, 0 off.
            thinking_config=types.ThinkingConfig(thinking_budget=-1 if reasoning else 0),
        )
        try:
            response = self._client.models.generate_content(
                model=model, contents=prompt, config=config
            )
        except genai_errors.APIError as exc:
            # Google reports an invalid key as 400 API_KEY_INVALID, not 401/403,
            # so a status-code check alone can't catch it — hence the message
            # match (case-insensitive to survive wording drift).
            if "api key" in str(exc).lower() or getattr(exc, "code", None) in (401, 403):
                raise ProviderAuthError(
                    "Gemini rejected the API key — re-set the GEMINI_API_KEY secret"
                ) from exc
            raise ProviderError(f"Gemini API error on {model}: {exc}") from exc
        parsed = response.parsed
        if not isinstance(parsed, schema):
            raise ProviderError(
                f"{model} returned unparseable output: {response.text!r:.200}"
            )
        meta = response.usage_metadata
        usage = Usage(
            input_tokens=(meta.prompt_token_count or 0) if meta else 0,
            output_tokens=(meta.candidates_token_count or 0) if meta else 0,
            thinking_tokens=(meta.thoughts_token_count or 0) if meta else 0,
        )
        return ProviderResponse(parsed=parsed, usage=usage, model=model)
