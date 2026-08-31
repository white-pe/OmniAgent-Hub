"""Minimal client for WeCom access tokens and application text messages."""

from __future__ import annotations

import json
from dataclasses import dataclass

import httpx


class WeComRequestError(RuntimeError):
    pass


@dataclass(frozen=True)
class WeComAccessToken:
    value: str
    expires_in: int


class WeComApiClient:
    base_url = "https://qyapi.weixin.qq.com/cgi-bin"

    def __init__(self, timeout_seconds: float) -> None:
        self.timeout = httpx.Timeout(
            timeout_seconds, connect=min(timeout_seconds, 10.0)
        )

    async def access_token(self, corp_id: str, corp_secret: str) -> WeComAccessToken:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/gettoken",
                    params={"corpid": corp_id, "corpsecret": corp_secret},
                )
        except httpx.RequestError as exc:
            raise WeComRequestError(f"Cannot connect to WeCom: {exc}") from exc
        data = self._data(response)
        self._assert_success(data)
        token = data.get("access_token")
        if not isinstance(token, str) or not token:
            raise WeComRequestError("WeCom token response is missing access_token")
        return WeComAccessToken(token, int(data.get("expires_in", 7200)))

    async def send_text(
        self,
        *,
        access_token: str,
        user_id: str,
        agent_id: int,
        content: str,
    ) -> None:
        payload = {
            "touser": user_id,
            "msgtype": "text",
            "agentid": agent_id,
            "text": {"content": content},
            "safe": 0,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/message/send",
                    params={"access_token": access_token},
                    json=payload,
                )
        except httpx.RequestError as exc:
            raise WeComRequestError(f"Cannot send WeCom message: {exc}") from exc
        data = self._data(response)
        self._assert_success(data)
        invalid = data.get("invaliduser")
        if isinstance(invalid, str) and invalid:
            raise WeComRequestError(f"WeCom rejected user: {invalid}")

    @staticmethod
    def _data(response: httpx.Response) -> dict[str, object]:
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise WeComRequestError(
                f"WeCom returned HTTP {response.status_code} with invalid JSON"
            ) from exc
        if not isinstance(data, dict):
            raise WeComRequestError("WeCom returned an invalid response")
        if not response.is_success:
            raise WeComRequestError(
                f"WeCom returned HTTP {response.status_code}: {data}"
            )
        return data

    @staticmethod
    def _assert_success(data: dict[str, object]) -> None:
        try:
            error_code = int(data.get("errcode", -1))
        except (TypeError, ValueError) as exc:
            raise WeComRequestError("WeCom response is missing errcode") from exc
        if error_code != 0:
            message = str(data.get("errmsg", "unknown error"))
            raise WeComRequestError(f"WeCom error {error_code}: {message}")
