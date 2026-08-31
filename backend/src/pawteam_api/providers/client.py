"""Small OpenAI-compatible client used without a heavyweight agent framework."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx


class ProviderRequestError(RuntimeError):
    """A safe-to-display upstream Provider error."""


class OpenAICompatibleClient:
    def __init__(self, base_url: str, api_key: str, timeout_seconds: float) -> None:
        self.completions_url = f"{base_url.rstrip('/')}/chat/completions"
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        self.timeout = httpx.Timeout(
            timeout_seconds, connect=min(timeout_seconds, 10.0)
        )

    async def test(self, model: str) -> str:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "Reply with OK only."}],
            "temperature": 0,
            "max_tokens": 16,
            "stream": False,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    self.completions_url, headers=self.headers, json=payload
                )
        except httpx.TimeoutException as exc:
            raise ProviderRequestError("Provider request timed out") from exc
        except httpx.RequestError as exc:
            raise ProviderRequestError(f"Cannot connect to Provider: {exc}") from exc

        if not response.is_success:
            raise ProviderRequestError(self._response_error(response))
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ProviderRequestError(
                "Provider returned an invalid completion response"
            ) from exc
        return str(content)

    async def complete(
        self,
        *,
        model: str,
        prompt: str,
        system_prompt: str | None,
        temperature: float,
        max_tokens: int,
    ) -> str:
        """Return one non-streaming completion for structured generation tasks."""

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    self.completions_url, headers=self.headers, json=payload
                )
        except httpx.TimeoutException as exc:
            raise ProviderRequestError("Provider request timed out") from exc
        except httpx.RequestError as exc:
            raise ProviderRequestError(f"Cannot connect to Provider: {exc}") from exc

        if not response.is_success:
            raise ProviderRequestError(self._response_error(response))
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ProviderRequestError(
                "Provider returned an invalid completion response"
            ) from exc
        if not isinstance(content, str) or not content.strip():
            raise ProviderRequestError("Provider returned empty completion content")
        return content

    async def stream(
        self,
        *,
        model: str,
        prompt: str,
        system_prompt: str | None,
        temperature: float,
    ) -> AsyncIterator[str]:
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        async for content in self.stream_messages(
            model=model,
            messages=messages,
            temperature=temperature,
        ):
            yield content

    async def stream_messages(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
    ) -> AsyncIterator[str]:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST", self.completions_url, headers=self.headers, json=payload
                ) as response:
                    if not response.is_success:
                        await response.aread()
                        raise ProviderRequestError(self._response_error(response))
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            return
                        if not data:
                            continue
                        try:
                            chunk = json.loads(data)
                            content = chunk["choices"][0]["delta"].get("content")
                        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
                            continue
                        if content:
                            yield str(content)
        except httpx.TimeoutException as exc:
            raise ProviderRequestError("Provider stream timed out") from exc
        except httpx.RequestError as exc:
            raise ProviderRequestError(f"Provider stream failed: {exc}") from exc

    @staticmethod
    def _response_error(response: httpx.Response) -> str:
        detail = ""
        try:
            body = response.json()
            error = body.get("error", body) if isinstance(body, dict) else body
            if isinstance(error, dict):
                detail = str(error.get("message", ""))
            elif isinstance(error, str):
                detail = error
        except json.JSONDecodeError:
            detail = response.text[:300]
        detail = detail.strip() or response.reason_phrase
        return f"Provider returned HTTP {response.status_code}: {detail}"
