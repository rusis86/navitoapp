"""Dell TechDirect API 클라이언트 (서비스태그 -> 출하 구성 정보).

사용 API
  - OAuth2 토큰:      POST {base}/auth/oauth/v2/token  (client_credentials)
  - Asset Components: GET  {base}/PROD/sbil/eapi/v5/asset-components?servicetag=XXXX

API 키는 Dell TechDirect(https://tdm.dell.com) 에서 'Warranty / Asset' API 를
신청해 발급받는다. 응답 필드명은 버전에 따라 조금씩 달라 방어적으로 파싱한다.
"""
from __future__ import annotations

import os
import re
import time

import httpx

from .dell_config import asset_to_groups, groups_to_items
from .mock_data import DEMO_ASSETS

TAG_RE = re.compile(r"^[A-Z0-9]{5,10}$")


class DellApiError(Exception):
    pass


class DellClient:
    def __init__(self, client_id: str | None = None, client_secret: str | None = None,
                 base_url: str | None = None, timeout: float = 20.0):
        self.client_id = client_id or os.getenv("DELL_CLIENT_ID", "")
        self.client_secret = client_secret or os.getenv("DELL_CLIENT_SECRET", "")
        self.base_url = (base_url or os.getenv("DELL_API_BASE")
                         or "https://apigtwb2c.us.dell.com").rstrip("/")
        self.timeout = timeout
        self._token: str | None = None
        self._token_exp = 0.0

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def _get_token(self) -> str:
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        r = httpx.post(
            f"{self.base_url}/auth/oauth/v2/token",
            data={"grant_type": "client_credentials",
                  "client_id": self.client_id, "client_secret": self.client_secret},
            timeout=self.timeout,
        )
        if r.status_code != 200:
            raise DellApiError(f"토큰 발급 실패 (HTTP {r.status_code}): {r.text[:200]}")
        body = r.json()
        self._token = body["access_token"]
        self._token_exp = time.time() + int(body.get("expires_in", 3600))
        return self._token

    def asset_components(self, service_tag: str) -> dict:
        r = httpx.get(
            f"{self.base_url}/PROD/sbil/eapi/v5/asset-components",
            params={"servicetag": service_tag},
            headers={"Authorization": f"Bearer {self._get_token()}",
                     "Accept": "application/json"},
            timeout=self.timeout,
        )
        if r.status_code != 200:
            raise DellApiError(f"구성 조회 실패 (HTTP {r.status_code}): {r.text[:200]}")
        data = r.json()
        if isinstance(data, list):
            data = data[0] if data else {}
        if data.get("invalid"):
            raise DellApiError(f"유효하지 않은 서비스태그: {service_tag}")
        return data


def normalize_asset(data: dict) -> dict:
    """API 응답 -> {service_tag, model, ship_date, items:[{description, quantity, ...}]}"""
    model = (data.get("systemDescription") or data.get("productLineDescription")
             or data.get("productId") or "Unknown")
    groups = asset_to_groups(data.get("components") or [])
    found_model, items = groups_to_items(groups)
    return {
        "service_tag": data.get("serviceTag"),
        "model": model if model != "Unknown" else (found_model or model),
        "ship_date": data.get("shipDate"),
        "country": data.get("countryCode"),
        "items": items,
    }


def lookup(service_tag: str, client: DellClient | None = None) -> dict:
    tag = service_tag.strip().upper()
    if tag in DEMO_ASSETS:
        result = normalize_asset(DEMO_ASSETS[tag])
        result["source"] = "demo"
        return result
    if not TAG_RE.match(tag):
        raise DellApiError("서비스태그 형식이 올바르지 않습니다 (영문/숫자 5~10자).")
    client = client or DellClient()
    if not client.configured:
        raise DellApiError(
            "Dell TechDirect API 키가 설정되지 않았습니다. DELL_CLIENT_ID / DELL_CLIENT_SECRET "
            "환경변수를 설정하거나, 데모 태그(" + ", ".join(DEMO_ASSETS) + ") 또는 "
            "'구성 직접 입력'을 사용하세요."
        )
    result = normalize_asset(client.asset_components(tag))
    result["source"] = "dell-techdirect"
    return result
