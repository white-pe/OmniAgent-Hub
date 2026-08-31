"""Small XML boundary for WeCom callbacks."""

from __future__ import annotations

from dataclasses import dataclass
from xml.etree import ElementTree


class WeComXmlError(ValueError):
    pass


def encrypted_value(body: bytes) -> str:
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as exc:
        raise WeComXmlError("Invalid callback XML") from exc
    value = root.findtext("Encrypt")
    if not value:
        raise WeComXmlError("Callback XML does not contain Encrypt")
    return value


@dataclass(frozen=True)
class WeComInbound:
    corp_id: str
    user_id: str
    message_type: str
    content: str
    message_id: str
    created_at: str


def parse_plain_message(body: bytes) -> WeComInbound:
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as exc:
        raise WeComXmlError("Invalid decrypted callback XML") from exc

    def required(name: str) -> str:
        value = root.findtext(name)
        if value is None or not value.strip():
            raise WeComXmlError(f"Callback XML does not contain {name}")
        return value.strip()

    message_type = required("MsgType")
    content = (root.findtext("Content") or "").strip()
    message_id = (root.findtext("MsgId") or "").strip()
    created_at = (root.findtext("CreateTime") or "").strip()
    user_id = required("FromUserName")
    if not message_id:
        message_id = f"{user_id}:{created_at}:{message_type}"
    return WeComInbound(
        corp_id=required("ToUserName"),
        user_id=user_id,
        message_type=message_type,
        content=content,
        message_id=message_id,
        created_at=created_at,
    )
