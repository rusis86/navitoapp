"""Dell 부품 설명(itemDescription) 문자열을 하드웨어 구성으로 분류/파싱."""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict

from . import catalog


@dataclass
class Component:
    category: str          # cpu, memory, drive, controller, boss, nic, gpu, psu, fan
    description: str
    quantity: int
    attrs: dict = field(default_factory=dict)


@dataclass
class HardwareConfig:
    model: str
    form_factor: str
    components: list[Component] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)       # 전력 무관 항목
    unrecognized: list[str] = field(default_factory=list)  # 분류 실패 항목
    factory_profile: str | None = None  # 주문 시 지정된 BIOS 프로파일 (예: 384-BBBL 성능 BIOS 설정)

    def of(self, category: str) -> list[Component]:
        return [c for c in self.components if c.category == category]

    def to_dict(self) -> dict:
        return asdict(self)


# dell.com 한국어 구성 설명 -> 영문 키워드 (긴 것부터 치환)
_KO_EN = [
    ("매우 고성능", "Very High Performance"), ("고성능", "High Performance"),
    ("전원 공급 장치", "Power Supply"), ("전원 코드", "Power Cord"), ("점퍼 코드", "Jumper Cord"),
    ("파이버 채널", "Fibre Channel"), ("옵티컬 트랜시버", "Optical Transceiver"),
    ("트랜시버", "Transceiver"), ("옵티컬", "Optical"),
    ("듀얼 포트", "Dual Port"), ("쿼드 포트", "Quad Port"), ("싱글 포트", "Single Port"),
    ("싱글 랭크", "Single Rank"), ("듀얼 랭크", "Dual Rank"), ("쿼드 랭크", "Quad Rank"),
    ("인텔", "Intel"), ("제온", "Xeon"), ("플래티넘", "Platinum"), ("골드", "Gold"),
    ("실버", "Silver"), ("브론즈", "Bronze"), ("프로세서", "Processor"),
    ("핫플러그", "Hot-plug"), ("중복", "Redundant"), ("듀얼", "Dual"),
    ("어댑터", "Adapter"), ("드라이브", "Drive"), ("인치", "in"), ("섀시", "Chassis"),
    ("히트싱크", "Heatsink"), ("마더보드", "Motherboard"), ("라이저", "Riser"),
    ("레일", "Rail"), ("베젤", "Bezel"), ("블랭크", "Blank"), ("배송", "Shipping"),
    ("케이블", "Cable"), ("메자닌", "Mezzanine"), ("팬", "Fan"), ("서버", "Server"),
    ("성능 BIOS 설정", "Performance BIOS Settings"),
    ("필요 없음", "None"), ("불필요", "None"), ("없음", "None"), ("미구성", "Unconfigured"),
]


def normalize_text(desc: str) -> str:
    d = desc
    for ko, en in _KO_EN:
        d = d.replace(ko, f" {en} ")
    return re.sub(r"\s+", " ", d).strip()


_NONE = re.compile(
    r"\b(none|not included|not installed|not required|blank|filler|disabled|unconfigured)\b",
    re.IGNORECASE)
_PERF_BIOS = re.compile(r"performance bios|enable performance mode", re.IGNORECASE)

# 전력과 무관하거나 무시할 항목
_IGNORE = re.compile(
    r"\b(no |none|not included|blank|bezel|rail|cable|cord|documentation|doc kit|"
    r"shipping|label|warranty|prosupport|support|service|software|license|"
    r"windows|vmware|esxi|red ?hat|ubuntu|suse|os |operating system|media|"
    r"heatsink|heat sink|idrac|jumper|keyboard|mouse|cma|cable management|"
    r"trusted platform|tpm|quick sync|openmanage|connectivity|static ip|luggage|energy star|"
    r"mechanical|chassis|drive slot|idrac\d* ?(enterprise|datacenter|express|basic)|"
    r"chassis intrusion|packaging|setup|install|deployment|dimm blank|"
    r"motherboard|system board|riser|configuration|unconfigured|raid ?\d+ |"
    r"performance bios|power saving|bios setting|uefi|front bezel|lcd)",
    re.IGNORECASE,
)

_CPU = re.compile(r"\b(xeon|epyc|pentium)\b", re.IGNORECASE)
_MEM = re.compile(r"(\d+)\s*GB\s*(RDIMM|LRDIMM|UDIMM|DIMM|DDR\d)", re.IGNORECASE)
_PSU = re.compile(r"power supply|\bPSU\b", re.IGNORECASE)
_GPU = re.compile(
    r"\b(nvidia|tesla|instinct|radeon|flex \d{3}|gpu|accelerator)\b", re.IGNORECASE
)
_BOSS = re.compile(r"\bBOSS\b", re.IGNORECASE)
_CTRL = re.compile(r"\b(PERC|HBA\d{3}|H\d{3}[A-Z]?\b|S1[56]0)", re.IGNORECASE)
_DRIVE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(TB|GB)\b.*\b(SSD|HDD|NVME|RPM|hard drive|SAS|SATA|M\.2|E3\.S|U\.2)",
    re.IGNORECASE,
)
_NIC = re.compile(
    r"(\bGbE\b|\d+\s*Gb\b|ethernet|network|connectx|\bOCP\b|\bNIC\b|fibre channel|"
    r"\bLOM\b|rNDC|\bSFP|\bQSFP|\bBASE-T|\bHBA\b.*\bFC)",
    re.IGNORECASE,
)
_FAN = re.compile(r"\bfan", re.IGNORECASE)


def detect_form_factor(model: str) -> str:
    m = re.sub(r"(?i)poweredge|\s", "", model or "").upper()
    for key, ff in catalog.MODEL_FORM_FACTOR.items():
        if key in m:
            return ff
    if m.startswith("MX"):
        return "MODULAR"
    if m.startswith("T"):
        return "TOWER"
    rack = re.match(r"R(\d)(\d)", m)
    if rack:
        # R2xx/R3xx/R4xx/R6xx -> 1U, R5xx/R7xx -> 2U, R8xx/R9xx -> 2U/4U
        first = rack.group(1)
        if first in "2346":
            return "1U"
        if first in "57":
            return "2U"
        if first == "8":
            return "2U"
        if first == "9":
            return "4U"
    return "2U"


def _parse_cpu(desc: str) -> dict:
    attrs: dict = {"vendor": "AMD" if re.search(r"epyc", desc, re.I) else "Intel"}
    tdp = re.search(r"\((\d{2,3})\s*W\)", desc) or re.search(r"\b(\d{2,3})\s*W\b", desc)
    if tdp:
        attrs["tdp"] = int(tdp.group(1))
        attrs["tdp_source"] = "description"
    cores = re.search(r"(\d+)C\b|(\d+)\s*cores?", desc, re.I)
    if cores:
        attrs["cores"] = int(cores.group(1) or cores.group(2))

    model = None
    up = desc.upper()
    m = re.search(r"\b(E5-\d{4}\s*V\d)", up)
    if m:
        model = re.sub(r"(\d)\s*V", r"\1 V", m.group(1))
    if not model:
        m = re.search(r"\b(E-2\d{3}G?)\b", up)
        if m:
            model = m.group(1)
    if not model:
        # EPYC: 9654, 7H12, 75F3, 4584PX / Xeon: 6430, 8480+, 6438Y+, 6787P
        brand = re.search(r"XEON|EPYC", up)
        tail = up[brand.end():] if brand else up
        cands = re.findall(r"\b(\d[0-9A-Z]{3}[A-Z]{0,2}\+?)(?=[\s,(]|$)", tail)
        known = [c for c in cands if c in catalog.CPU_TDP or c.rstrip("+") in catalog.CPU_TDP]
        if known or cands:
            model = (known or cands)[0]
    if model:
        attrs["model"] = model
        if "tdp" not in attrs:
            tdp_val = catalog.CPU_TDP.get(model)
            if tdp_val is None:
                tdp_val = catalog.CPU_TDP.get(model.rstrip("+"))
            if tdp_val is not None:
                attrs["tdp"] = tdp_val
                attrs["tdp_source"] = "catalog"
    if "tdp" not in attrs:
        # 코어 수 기반 대략 추정
        c = attrs.get("cores", 16)
        attrs["tdp"] = int(min(400, 60 + c * 5))
        attrs["tdp_source"] = "estimated"
    return attrs


def _parse_memory(desc: str) -> dict:
    m = _MEM.search(desc)
    size = int(m.group(1)) if m else 32
    speed = re.search(r"(\d{4})\s*MT/s", desc, re.I)
    ddr = re.search(r"DDR(\d)", desc, re.I)
    if ddr:
        gen = f"DDR{ddr.group(1)}"
    elif speed:
        gen = "DDR5" if int(speed.group(1)) >= 4400 else "DDR4"
    else:
        gen = "DDR4"
    return {
        "size_gb": size,
        "generation": gen,
        "speed": int(speed.group(1)) if speed else None,
        "type": "LRDIMM" if re.search(r"LRDIMM", desc, re.I) else "RDIMM",
    }


def _parse_drive(desc: str) -> dict:
    m = _DRIVE.search(desc)
    cap = float(m.group(1)) if m else 0.0
    unit = m.group(2).upper() if m else "TB"
    cap_tb = cap if unit == "TB" else cap / 1000
    d = desc.upper()
    if "M.2" in d:
        kind = "SSD_M2"
    elif "NVME" in d or "E3.S" in d or "U.2" in d:
        kind = "SSD_NVME_GEN5" if re.search(r"GEN ?5|PCIE ?5", d) else "SSD_NVME"
    elif "SSD" in d or "SOLID STATE" in d:
        kind = "SSD_SAS" if re.search(r"\bSAS\b", d) else "SSD_SATA"
    elif "15K" in d:
        kind = "HDD_15K"
    elif "10K" in d:
        kind = "HDD_10K"
    else:
        kind = "HDD_7K_LARGE" if cap_tb >= 12 else "HDD_7K"
    return {"capacity_tb": round(cap_tb, 3), "kind": kind}


def _parse_controller(desc: str) -> dict:
    d = desc.upper().replace(" ", "")
    for key in sorted(catalog.CONTROLLER_POWER, key=len, reverse=True):
        if key in d:
            return {"model": key, "max_w": catalog.CONTROLLER_POWER[key]}
    return {"model": "unknown", "max_w": catalog.CONTROLLER_DEFAULT}


def _parse_nic(desc: str) -> dict:
    d = desc.upper()
    if "FIBRE CHANNEL" in d or re.search(r"\bFC\b|\bLPE\d|QLE\d", d):
        speed = re.search(r"(\d+)\s*GB", d)
        sp = int(speed.group(1)) if speed else 32
        ports = 2 if re.search(r"DUAL|2\s*PORT|2P\b", d) else (4 if re.search(r"QUAD|4\s*PORT", d) else 1)
        return {"type": "FC", "speed": sp, "ports": ports}
    speeds = [int(s) for s in re.findall(r"(\d+)\s*(?:/\d+)?\s*G(?:B|BE|BASE)", d)]
    # "10/25GbE" -> 25 사용
    multi = re.findall(r"(\d+)/(\d+)\s*GBE", d)
    for a, b in multi:
        speeds.append(int(b))
    speed = max([s for s in speeds if s in catalog.NIC_PORT_POWER] or [10])
    if re.search(r"QUAD|4\s*PORT|4P\b|4X", d):
        ports = 4
    elif re.search(r"DUAL|2\s*PORT|2P\b|2X", d):
        ports = 2
    elif re.search(r"SINGLE|1\s*PORT|1P\b", d):
        ports = 1
    else:
        ports = 2
    return {"type": "ETH", "speed": speed, "ports": ports}


def _parse_gpu(desc: str) -> dict:
    d = desc.upper()
    for key in sorted(catalog.GPU_TDP, key=len, reverse=True):
        if re.search(r"\b" + re.escape(key) + r"\b", d):
            tdp = catalog.GPU_TDP[key]
            w = re.search(r"\b(\d{2,3})\s*W\b", d)
            return {"model": key, "tdp": int(w.group(1)) if w else tdp}
    w = re.search(r"\b(\d{2,3})\s*W\b", d)
    return {"model": "unknown", "tdp": int(w.group(1)) if w else 250}


def _parse_psu(desc: str) -> dict:
    d = desc.upper()
    w = re.findall(r"(\d{3,4})\s*W", d)
    watts = max(int(x) for x in w) if w else 1100
    if "TITANIUM" in d:
        rating = "TITANIUM"
    elif "GOLD" in d:
        rating = "GOLD"
    else:
        rating = "PLATINUM"
    redundant = bool(re.search(r"REDUNDANT|1\+1|DUAL", d))
    count = 2 if redundant and re.search(r"DUAL|1\+1", d) else None
    return {"watts": watts, "rating": rating, "redundant": redundant, "count_hint": count}


def classify(description: str) -> str | None:
    """설명 문자열의 부품 카테고리를 반환. 무시 대상은 'ignore', 미분류는 None."""
    d = normalize_text(description)
    if not d:
        return "ignore"
    if _NONE.search(d):
        return "ignore"
    if re.search(r"transceiver|\boptic", d, re.I):
        return "transceiver"
    if _PSU.search(d):
        return "psu"
    if _CPU.search(d) and not re.search(r"heatsink|heat sink|upgrade kit|bios", d, re.I):
        return "cpu"
    if _MEM.search(d):
        return "memory"
    if _BOSS.search(d) and not re.search(r"blank|mechanical", d, re.I):
        return "boss"
    if re.search(r"connectx|\bGbE\b|ethernet|\bNIC\b|\bSFP|\bQSFP|\bOSFP|InfiniBand|\bNDR|\bHDR", d, re.I) \
            and not re.search(r"riser|cable|transceiver|optic", d, re.I):
        return "nic"
    if _GPU.search(d) and not re.search(r"enablement|ready|riser|cable|bracket|power cable", d, re.I):
        return "gpu"
    if _DRIVE.search(d) and not re.search(r"backplane|chassis with|blank", d, re.I):
        return "drive"
    if re.search(r"\bPERC\b|\bHBA\d{3}|\bH\d{3}[A-Z]?\b.*(RAID|controller|adapter|front|internal)", d, re.I) \
            and not re.search(r"chassis|slot|mechanical|shroud|cable", d, re.I):
        return "controller"
    if _NIC.search(d) and not re.search(r"riser|cable|transceiver|optic", d, re.I):
        return "nic"
    if _FAN.search(d):
        return "fan"
    if _IGNORE.search(d):
        return "ignore"
    return None


def build_config(model: str, items: list[dict]) -> HardwareConfig:
    """items: [{"description": str, "quantity": int}, ...]"""
    cfg = HardwareConfig(model=model or "Unknown", form_factor=detect_form_factor(model))
    for it in items:
        desc = str(it.get("description", "")).strip()
        qty = int(it.get("quantity") or 1)
        if qty <= 0:
            continue
        norm = normalize_text(desc)
        if _PERF_BIOS.search(norm):
            cfg.factory_profile = "performance"
        cat = "ignore" if it.get("info_only") else classify(desc)
        if cat == "ignore":
            cfg.ignored.append(desc)
            continue
        if cat is None:
            cfg.unrecognized.append(desc)
            continue
        parser = {
            "cpu": _parse_cpu, "memory": _parse_memory, "drive": _parse_drive,
            "controller": _parse_controller, "nic": _parse_nic, "gpu": _parse_gpu,
            "psu": _parse_psu, "boss": lambda _d: {}, "fan": _parse_fan,
            "transceiver": _parse_transceiver,
        }[cat]
        # 해석은 영문 정규화 문자열 + (있으면) Dell 부품 설명으로
        detail = it.get("detail") or ""
        cfg.components.append(Component(cat, desc, qty, parser(f"{norm} {detail}".strip())))
    return cfg


def _parse_fan(desc: str) -> dict:
    d = desc.upper()
    if "VERY HIGH PERFORMANCE" in d or "VHP" in d:
        return {"tier": "VHP", "multiplier": 1.6}
    if "HIGH PERFORMANCE" in d or "GOLD" in d:
        return {"tier": "HP", "multiplier": 1.3}
    return {"tier": "STD", "multiplier": 1.0}


_LINE = re.compile(r"^\s*(?:(\d+)\s*[xX×*]\s+|(\d+)\s*[\t,|]\s*)?(.+?)\s*$")


def parse_text_config(text: str) -> list[dict]:
    """붙여넣은 구성 텍스트를 items 리스트로 변환.

    지원 형식(라인 단위):
      2 x Intel Xeon Gold 6430 ...
      12, 64GB RDIMM, 4800MT/s ...
      Intel Xeon Gold 6430 ...        (수량 1)
    """
    items = []
    for line in text.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        m = _LINE.match(line)
        if not m:
            continue
        qty = int(m.group(1) or m.group(2) or 1)
        items.append({"description": m.group(3), "quantity": qty})
    return items


def _parse_transceiver(desc: str) -> dict:
    d = desc.upper()
    if re.search(r"QSFP|OSFP|100G|200G|400G", d):
        kind = "QSFP"
    elif re.search(r"SFP28|25G", d):
        kind = "SFP28"
    else:
        kind = "SFP"
    return {"kind": kind}
