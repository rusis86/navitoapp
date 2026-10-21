"""Dell 주문 구성 데이터(SKU 그룹 + 부품 행) -> 계산용 items.

dell.com 지원 페이지에서 내려받은 구성 CSV 와 TechDirect asset-components API 는
같은 구조를 가진다.

    구성 요소(SKU : 설명)             부품 번호  설명(부품)                         수량
    338-CHSK : 인텔 제온 골드 6434 ...  VVJN7     CLP,LKG,CPU,...                    1
                                        8M9XX     PRC,6434,3.7,ISPR,8C,195W,S3        2
    370-BBRQ : 16GB RDIMM, 5600MT/s    5DR48     DIMM,16GB,5600,1RX8,16G,DDR5,R      1   (x12 행)

SKU 제목으로 부품 종류를 판별하고, 수량은 그 종류의 '핵심 부품' 행(PRC, DIMM, SSDR ...)
수량 합계로 계산한다. 나사/라벨/INFO 행은 수량에 포함하지 않는다.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field

from .parser import classify, normalize_text

# 카테고리별 핵심 부품 행 (Dell 부품 설명 접두어)
KEY_PART = {
    "cpu": re.compile(r"^PRC\b", re.I),
    "memory": re.compile(r"^DIMM\b", re.I),
    "drive": re.compile(r"^(SSDR|SSD|HDD|HD,|NVME|DRV)", re.I),
    "nic": re.compile(r"^(ASSY,)?CRD,(NTWK|CTL|LOM|OCP)|^ASSY,CRD,LOM", re.I),
    "controller": re.compile(r"^(ASSY,)?CRD,CTL", re.I),
    "psu": re.compile(r"^PWR ?SPLY|^ASSY,PWR,SPLY|^PSU,", re.I),
    "gpu": re.compile(r"^(ASSY,)?(CRD,)?(GPU|GRPH|ACCEL|ACLTR)", re.I),
    "boss": re.compile(r"^(ASSY,)?CRD,(CTL,)?BOSS", re.I),
    "transceiver": re.compile(r"transceiver|^XCVR|^(ASSY,)?OPT", re.I),
    "fan": re.compile(r"^ASSY,FAN", re.I),
}

# 물리 부품이 아닌 행 (그룹 전체가 이것뿐이면 전력 무관)
NON_PHYSICAL = re.compile(
    r"^(INFO|Information|SI[ ,]|System Integration|SRV,(SW|DRVR|MZR|LICENSE)|Service Charge|"
    r"DSK PROG|DPK|LBL|AW,LBL|ASSY,LBL|Label|GDE|INSTR|KIT,SHP|SHP MTL|\*+$)",
    re.I,
)

MODEL_RE = re.compile(r"PowerEdge\s+([A-Z]{1,3}\d{3,4}[A-Za-z]{0,3})", re.I)
TAG_RE = re.compile(r"\b([A-Z0-9]{7})\b")


@dataclass
class SkuGroup:
    sku: str
    title: str
    parts: list[tuple[str, str, int]] = field(default_factory=list)  # (part_no, desc, qty)


def _qty(v) -> int:
    try:
        return int(float(str(v).strip() or 0))
    except ValueError:
        return 0


def group_quantity(category: str | None, g: SkuGroup) -> tuple[int, str]:
    """그룹의 부품 수량과 대표 부품 설명."""
    pat = KEY_PART.get(category or "")
    if pat:
        hits = [(d, q) for _, d, q in g.parts if pat.search(d)]
        if hits:
            return sum(q for _, q in hits), hits[0][0]
    if g.parts and all(not pn for pn, _, _ in g.parts):
        # 부품 상세가 없는 데이터(SKU 행만 존재): SKU 수량 사용
        return max(1, sum(q for _, _, q in g.parts)), ""
    return 1, ""


def groups_to_items(groups: list[SkuGroup]) -> tuple[str | None, list[dict]]:
    """SKU 그룹 목록 -> (모델명, items).

    물리 부품 행이 하나도 없는 그룹(INFO/SI/라벨 등)은 info_only 로 표시해
    계산에서 제외한다. (예: '5600MT/s RDIMMs' 는 주문 정보일 뿐 실제 DIMM 이 아님)
    """
    model = None
    items = []
    for g in groups:
        title = g.title or (g.parts[0][1] if g.parts else "")
        if not model:
            m = MODEL_RE.search(title)
            if m and re.search(r"server|서버", title, re.I) or (m and g.sku.startswith("210-")):
                model = f"PowerEdge {m.group(1).upper()}"
        physical = [p for p in g.parts if not NON_PHYSICAL.search(p[1].strip())]
        cat = classify(title)
        qty, detail = group_quantity(cat, g)
        item = {"description": title, "quantity": qty, "sku": g.sku, "detail": detail}
        if g.parts and not physical:
            item["info_only"] = True
        items.append(item)
    if not model:
        for g in groups:
            m = MODEL_RE.search(g.title)
            if m:
                model = f"PowerEdge {m.group(1).upper()}"
                break
    return model, items


def parse_dell_csv(text: str, filename: str | None = None) -> dict:
    """dell.com 구성 CSV 텍스트 -> {model, service_tag, items}."""
    text = text.lstrip("﻿")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        raise ValueError("CSV 가 비어 있습니다.")
    header = [h.strip().lower() for h in rows[0]]
    if any(k in " ".join(header) for k in ("구성", "component", "부품", "part", "설명", "description")):
        rows = rows[1:]
    groups: list[SkuGroup] = []
    for r in rows:
        if len(r) < 3 or not any(c.strip() for c in r):
            continue
        comp = r[0].strip()
        part_no = r[1].strip() if len(r) > 1 else ""
        desc = r[2].strip() if len(r) > 2 else ""
        qty = _qty(r[3]) if len(r) > 3 else 1
        if comp:
            sku, _, title = comp.partition(" : ")
            if not title:
                sku, title = "", comp
            groups.append(SkuGroup(sku.strip(), title.strip()))
        if not groups:
            groups.append(SkuGroup("", desc))
        if part_no or desc:
            groups[-1].parts.append((part_no, desc, qty))
    if not groups:
        raise ValueError("구성 항목을 찾지 못했습니다. dell.com 에서 내려받은 구성 CSV 인지 확인하세요.")
    model, items = groups_to_items(groups)
    tag = None
    if filename:
        stem = re.sub(r"\.[^.]+$", "", filename.rsplit("/", 1)[-1]).upper()
        m = TAG_RE.findall(stem)
        tag = m[-1] if m else None
    return {"model": model or "PowerEdge", "service_tag": tag, "items": items}


def asset_to_groups(components: list[dict]) -> list[SkuGroup]:
    """TechDirect asset-components 응답 -> SKU 그룹."""
    groups: dict[str, SkuGroup] = {}
    for c in components:
        sku = c.get("itemNumber") or c.get("skuNumber") or ""
        title = (c.get("itemDescription") or "").strip()
        key = sku or title
        g = groups.setdefault(key, SkuGroup(sku, title))
        pdesc = (c.get("partDescription") or "").strip()
        qty = _qty(c.get("partQuantity") or c.get("quantity") or 1)
        if pdesc or c.get("partNumber"):
            g.parts.append((c.get("partNumber") or "", pdesc, qty))
        elif not g.parts:
            # 부품 상세가 없는 응답: SKU 행 수량을 그대로 사용
            g.parts.append(("", title, qty))
    return list(groups.values())
