"""Masking of identifiers that come from the organizer's data (pixel/account IDs, hashes, domains).

Reports and Reason texts can end up in a public repo, so full identifiers must not appear there:
  - long numeric IDs / hashes -> first 4 + "…" + last 4     1234567890123456 -> 1234…3456
  - domains and URLs          -> host only, dots defanged    https://scam-example.live/x -> scam-example[.]live
Masking is applied where texts are created (engine.similarity.describe, cluster labels) and,
as a safety net, to whole reports (`mask_text`).
"""
from __future__ import annotations

import re
from typing import Any

_HOST = re.compile(r"^(?:[a-z][a-z0-9+.-]*://)?(?:[^/@\s]*@)?((?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,})(?::\d+)?(?:[/?#].*)?$")
_LONG_DIGITS = re.compile(r"\d{8,}")
_LONG_HEX = re.compile(r"\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{12,}\b", re.IGNORECASE)


def mask_id(s: str) -> str:
    """1234567890123456 -> 1234…3456 (strings shorter than 8 characters are left as they are)."""
    return s if len(s) < 8 else f"{s[:4]}…{s[-4:]}"


def defang_host(host: str) -> str:
    return host.replace(".", "[.]")


def mask_value(value: Any) -> str:
    """Mask one value as shown in a Reason: a domain/URL is defanged, long IDs/hashes are shortened."""
    s = str(value).strip()
    m = _HOST.match(s)
    if m:
        return defang_host(m.group(1))
    s = _LONG_DIGITS.sub(lambda x: mask_id(x.group(0)), s)
    return _LONG_HEX.sub(lambda x: mask_id(x.group(0)), s)


def mask_text(text: str) -> str:
    """Safety net for whole documents: shorten long digit runs and long hex hashes everywhere.

    Domains are not touched here (a free-text scan would also hit file names such as labels.yaml);
    they are defanged where they are produced, by `mask_value`.
    """
    text = _LONG_DIGITS.sub(lambda x: mask_id(x.group(0)), text)
    return _LONG_HEX.sub(lambda x: mask_id(x.group(0)), text)
