"""FastAPI 앱: 서비스태그 조회 + 전력 추정 API 및 웹 UI."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .dell_api import DellApiError, DellClient, lookup
from .estimator import PROFILES, estimate
from .mock_data import DEMO_ASSETS
from .parser import build_config, parse_text_config

STATIC = Path(__file__).parent / "static"

app = FastAPI(title="Dell PowerEdge 전력 계산기", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
_client = DellClient()


class Options(BaseModel):
    utilization: float = Field(0.5, ge=0, le=1, description="일반(Typical) 부하율")
    kwh_rate: float = Field(180.0, ge=0, description="전기요금 (원/kWh)")
    pue: float = Field(1.0, ge=1, le=3)
    voltage: float = Field(220.0, gt=0)
    power_cap: float | None = Field(None, gt=0, description="iDRAC Power Cap (W)")


class Item(BaseModel):
    description: str
    quantity: int = 1


class ManualRequest(BaseModel):
    model: str = "PowerEdge"
    items: list[Item] | None = None
    text: str | None = Field(None, description="'2 x 부품설명' 형식의 라인 텍스트")
    options: Options = Options()


def _run(model: str, items: list[dict], opts: Options, meta: dict | None = None) -> dict:
    cfg = build_config(model, items)
    result = estimate(cfg, utilization=opts.utilization, kwh_rate=opts.kwh_rate,
                      pue=opts.pue, voltage=opts.voltage, power_cap=opts.power_cap)
    result["config"] = cfg.to_dict()
    result["asset"] = meta or {}
    return result


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/info")
def info():
    return {
        "dell_api_configured": _client.configured,
        "demo_tags": list(DEMO_ASSETS),
        "profiles": [{"key": p.key, "name": p.name, "bios": p.bios,
                      "description": p.description} for p in PROFILES.values()],
    }


@app.get("/api/servicetag/{tag}")
def by_service_tag(
    tag: str,
    utilization: float = Query(0.5, ge=0, le=1),
    kwh_rate: float = Query(180.0, ge=0),
    pue: float = Query(1.0, ge=1, le=3),
    voltage: float = Query(220.0, gt=0),
    power_cap: float | None = Query(None, gt=0),
):
    try:
        asset = lookup(tag, _client)
    except DellApiError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # 네트워크 오류 등
        raise HTTPException(status_code=502, detail=f"Dell API 호출 오류: {e}")
    opts = Options(utilization=utilization, kwh_rate=kwh_rate, pue=pue,
                   voltage=voltage, power_cap=power_cap)
    meta = {k: asset.get(k) for k in ("service_tag", "ship_date", "country", "source")}
    return _run(asset["model"], asset["items"], opts, meta)


@app.post("/api/estimate")
def manual(req: ManualRequest):
    items = [i.model_dump() for i in req.items] if req.items else []
    if req.text:
        items += parse_text_config(req.text)
    if not items:
        raise HTTPException(status_code=400, detail="구성 항목이 없습니다.")
    return _run(req.model, items, req.options, {"source": "manual"})
