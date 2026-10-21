"""하드웨어 구성 + BIOS 시스템 프로파일 -> 전력 추정.

모델 개요
---------
각 부품은 (idle, max) 전력을 가지며, 부하율 u(0~1)에서
    P(u) = idle + (max - idle) * u ** curve
로 계산한다. Dell BIOS 시스템 프로파일은 다음에 영향을 준다.

* CPU: C-state 허용 여부(유휴 전력), Turbo 여부(최대 전력), 주파수 스케일링(곡선)
* 메모리: 최대 동작 주파수 제한(Low Power 시 감소), 리프레시/절전
* 팬: 프로파일별 최소 팬 속도(Thermal Profile)

DC 합계 -> PSU 효율 곡선 -> 벽전원(AC) 전력으로 환산한다.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import catalog
from .parser import HardwareConfig


@dataclass(frozen=True)
class Profile:
    key: str
    name: str
    bios: str
    description: str
    cpu_idle_frac: float   # 유휴 시 CPU 전력 / TDP
    cpu_max_frac: float    # 100% 부하 시 CPU 전력 / TDP
    cpu_curve: float       # <1: 중간 부하에서 전력이 높음(주파수 고정), >1: 절전 스케일링
    mem_factor: float      # 메모리 최대 전력 배율
    mem_idle_factor: float
    fan_floor: float       # 팬 최소 속도 비율(전력 기준)
    fan_max: float         # 최대 부하 시 팬 전력 비율


PROFILES: dict[str, Profile] = {
    "performance": Profile(
        key="performance",
        name="퍼포먼스 (Performance)",
        bios="System Profile = Performance",
        description="C-State/C1E 비활성, Turbo 활성, Uncore 최대, 메모리 최대 주파수. "
                    "지연시간 최소화, 유휴 전력이 가장 높음.",
        cpu_idle_frac=0.45, cpu_max_frac=1.0, cpu_curve=0.7,
        mem_factor=1.0, mem_idle_factor=1.0,
        fan_floor=0.30, fan_max=0.75,
    ),
    "balanced": Profile(
        key="balanced",
        name="밸런스 (Performance Per Watt - DAPC)",
        bios="System Profile = Performance Per Watt (DAPC)",
        description="Dell 기본값. C-State 활성, Turbo 활성, 하드웨어 P-State(DAPC) 제어. "
                    "부하에 따라 전력이 비례적으로 변함.",
        cpu_idle_frac=0.18, cpu_max_frac=1.0, cpu_curve=1.0,
        mem_factor=1.0, mem_idle_factor=0.9,
        fan_floor=0.18, fan_max=0.65,
    ),
    "ppw_os": Profile(
        key="ppw_os",
        name="밸런스 (Performance Per Watt - OS)",
        bios="System Profile = Performance Per Watt (OS)",
        description="C-State 활성, Turbo 활성, P-State를 OS 전원정책(governor)이 제어. "
                    "OS가 balanced/ondemand 정책일 때 기준. AMD 플랫폼의 출하 기본값.",
        cpu_idle_frac=0.20, cpu_max_frac=1.0, cpu_curve=0.95,
        mem_factor=1.0, mem_idle_factor=0.9,
        fan_floor=0.18, fan_max=0.65,
    ),
    "low_power": Profile(
        key="low_power",
        name="저전력 (Custom - Power Saving)",
        bios="System Profile = Custom: Turbo Off, C-States On, "
             "Energy Efficient Policy = Power, Memory Freq = Max Reliability/Power Saving",
        description="Turbo 비활성(기본 클럭 이하), 깊은 C-State, 메모리 주파수 하향, "
                    "Energy Efficient Policy=Power. 성능 10~25% 감소 가능.",
        cpu_idle_frac=0.13, cpu_max_frac=0.80, cpu_curve=1.15,
        mem_factor=0.85, mem_idle_factor=0.8,
        fan_floor=0.12, fan_max=0.50,
    ),
}

DEFAULT_UTILIZATION = 0.5  # '일반(Typical)' 부하율


def _lerp_eff(points: list[tuple[float, float]], load: float) -> float:
    load = max(0.0, min(1.0, load))
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 <= load <= x1:
            return y0 + (y1 - y0) * (load - x0) / (x1 - x0)
    return points[-1][1]


def _scale(idle: float, mx: float, u: float, curve: float = 1.0) -> float:
    return idle + (mx - idle) * (max(0.0, min(1.0, u)) ** curve)


def component_power(cfg: HardwareConfig, prof: Profile, u: float) -> list[dict]:
    """부하율 u에서 부품별 DC 전력 목록."""
    rows: list[dict] = []

    def add(category: str, label: str, qty: int, each: float):
        rows.append({
            "category": category, "label": label, "quantity": qty,
            "watts_each": round(each, 1), "watts": round(each * qty, 1),
        })

    # CPU
    for c in cfg.of("cpu"):
        tdp = c.attrs["tdp"]
        each = _scale(tdp * prof.cpu_idle_frac, tdp * prof.cpu_max_frac, u, prof.cpu_curve)
        add("cpu", c.description, c.quantity, each)

    # 메모리
    for c in cfg.of("memory"):
        gen = c.attrs["generation"]
        table = catalog.DIMM_POWER.get(gen, catalog.DIMM_POWER["DDR4"])
        size = c.attrs["size_gb"]
        key = min(table, key=lambda k: abs(k - size))
        idle, mx = table[key]
        if c.attrs.get("type") == "LRDIMM":
            idle, mx = idle * 1.15, mx * 1.15
        each = _scale(idle * prof.mem_idle_factor, mx * prof.mem_factor, u)
        add("memory", c.description, c.quantity, each)

    # 드라이브 (스토리지 I/O 부하는 CPU 부하에 비례한다고 가정)
    for c in cfg.of("drive"):
        idle, mx = catalog.DRIVE_POWER[c.attrs["kind"]]
        add("drive", c.description, c.quantity, _scale(idle, mx, u))

    for c in cfg.of("controller"):
        mx = c.attrs["max_w"]
        add("controller", c.description, c.quantity,
            _scale(mx * catalog.CONTROLLER_IDLE_FRACTION, mx, u))

    for c in cfg.of("boss"):
        idle, mx = catalog.BOSS_POWER
        add("boss", c.description, c.quantity, _scale(idle, mx, u))

    for c in cfg.of("nic"):
        if c.attrs["type"] == "FC":
            table = catalog.FC_HBA_POWER
            key = min(table, key=lambda k: abs(k - c.attrs["speed"]))
            idle, mx = table[key]
            if c.attrs["ports"] >= 2:
                idle, mx = idle * 1.0, mx * (1 + 0.15 * (c.attrs["ports"] - 1))
        else:
            pi, pm = catalog.NIC_PORT_POWER[c.attrs["speed"]]
            bi, bm = catalog.NIC_BASE_POWER
            idle, mx = bi + pi * c.attrs["ports"], bm + pm * c.attrs["ports"]
        add("nic", c.description, c.quantity, _scale(idle, mx, u))

    for c in cfg.of("gpu"):
        tdp = c.attrs["tdp"]
        add("gpu", c.description, c.quantity,
            _scale(tdp * catalog.GPU_IDLE_FRACTION, tdp, u))

    # 플랫폼(메인보드, iDRAC, 백플레인)
    plat = catalog.FORM_FACTOR_PLATFORM[cfg.form_factor]
    add("platform", f"메인보드/iDRAC/백플레인 ({cfg.form_factor})", 1,
        _scale(*plat["base"], u))

    # 팬: 발열(=다른 부품 전력) 증가에 따라 증가. GPU 장착 시 팬 부하 상향.
    fan_mult = max([c.attrs.get("multiplier", 1.0) for c in cfg.of("fan")] or [1.0])
    if cfg.of("gpu") and cfg.form_factor in ("1U", "2U"):
        fan_mult = max(fan_mult, 1.3)
    fan_full = plat["fan"] * fan_mult
    fan = fan_full * (prof.fan_floor + (prof.fan_max - prof.fan_floor) * (u ** 2))
    add("fan", "시스템 팬", 1, fan)
    return rows


def psu_info(cfg: HardwareConfig) -> dict:
    psus = cfg.of("psu")
    if not psus:
        return {"watts": None, "count": 2, "rating": "PLATINUM", "assumed": True}
    p = psus[0]
    count = sum(c.quantity for c in psus)
    if count == 1 and p.attrs.get("count_hint"):
        count = p.attrs["count_hint"]
    return {"watts": p.attrs["watts"], "count": count, "rating": p.attrs["rating"],
            "assumed": False}


def _to_wall(dc: float, psu: dict) -> tuple[float, float]:
    """DC 부하 -> (AC 전력, 효율). PSU 간 부하 분담(load sharing) 가정."""
    count = max(1, psu["count"])
    cap = psu["watts"] or 1100
    load = dc / (cap * count)
    eff = _lerp_eff(catalog.PSU_EFFICIENCY[psu["rating"]], load)
    return dc / eff, eff


def default_profile_key(cfg: HardwareConfig) -> str:
    """출하 기본 BIOS System Profile.

    Intel 플랫폼: Performance Per Watt (DAPC)
    AMD 플랫폼:   Performance Per Watt (OS)  (DAPC 옵션 없음)
    """
    cpus = cfg.of("cpu")
    if cpus and cpus[0].attrs.get("vendor") == "AMD":
        return "ppw_os"
    return "balanced"


def available_profiles(cfg: HardwareConfig) -> list[str]:
    keys = list(PROFILES)
    if default_profile_key(cfg) == "ppw_os":
        keys.remove("balanced")  # AMD BIOS에는 DAPC가 없음
    # 기본설정을 맨 앞으로
    d = default_profile_key(cfg)
    return [d] + [k for k in keys if k != d]


def estimate(cfg: HardwareConfig, utilization: float = DEFAULT_UTILIZATION,
             kwh_rate: float = 180.0, pue: float = 1.0, voltage: float = 220.0,
             power_cap: float | None = None, profiles: list[str] | None = None) -> dict:
    psu = psu_info(cfg)
    default_key = default_profile_key(cfg)
    keys = profiles or available_profiles(cfg)
    results = []
    for key in keys:
        prof = PROFILES[key]
        points = {}
        for label, u in (("idle", 0.0), ("typical", utilization), ("max", 1.0)):
            rows = component_power(cfg, prof, u)
            dc = sum(r["watts"] for r in rows)
            ac, eff = _to_wall(dc, psu)
            capped = False
            if power_cap and ac > power_cap:
                ac, capped = power_cap, True
            points[label] = {
                "utilization": u,
                "dc_watts": round(dc, 1),
                "ac_watts": round(ac, 1),
                "psu_efficiency": round(eff, 3),
                "btu_per_hr": round(ac * 3.412, 0),
                "amps": round(ac / voltage / 0.98, 2),
                "capped": capped,
                "breakdown": rows,
            }
        typ = points["typical"]["ac_watts"]
        annual_kwh = typ * 8760 / 1000 * pue
        results.append({
            "key": prof.key,
            "is_default": prof.key == default_key,
            "name": prof.name,
            "bios": prof.bios,
            "description": prof.description,
            "points": points,
            "annual_kwh": round(annual_kwh, 0),
            "annual_cost": round(annual_kwh * kwh_rate, 0),
        })

    base = next((r for r in results if r["is_default"]), None)
    if base:
        for r in results:
            r["vs_default"] = {
                k: round(r["points"][k]["ac_watts"] - base["points"][k]["ac_watts"], 1)
                for k in ("idle", "typical", "max")
            }
            r["vs_default_cost"] = round(r["annual_cost"] - base["annual_cost"], 0)

    warnings = _warnings(cfg, psu, results)
    return {
        "model": cfg.model,
        "form_factor": cfg.form_factor,
        "psu": psu,
        "assumptions": {
            "typical_utilization": utilization,
            "kwh_rate": kwh_rate,
            "pue": pue,
            "voltage": voltage,
            "power_factor": 0.98,
            "power_cap": power_cap,
        },
        "default_profile": {
            "key": default_key,
            "name": PROFILES[default_key].name,
            "bios": PROFILES[default_key].bios,
            "points": {k: base["points"][k]["ac_watts"] for k in ("idle", "typical", "max")}
            if base else None,
            "annual_kwh": base["annual_kwh"] if base else None,
            "annual_cost": base["annual_cost"] if base else None,
        },
        "profiles": results,
        "warnings": warnings,
    }


def _warnings(cfg: HardwareConfig, psu: dict, results: list[dict]) -> list[str]:
    w = []
    if not cfg.of("cpu"):
        w.append("CPU 정보를 찾지 못했습니다. 결과가 크게 과소 추정될 수 있습니다.")
    if not cfg.of("memory"):
        w.append("메모리 정보를 찾지 못했습니다.")
    for c in cfg.of("cpu"):
        if c.attrs.get("tdp_source") == "estimated":
            w.append(f"CPU TDP를 코어 수로 추정했습니다: {c.description}")
    if psu["assumed"]:
        w.append("PSU 정보가 없어 1100W Platinum x2 를 가정했습니다.")
    elif psu["watts"]:
        peak = max(r["points"]["max"]["ac_watts"] for r in results)
        if psu["count"] >= 2 and peak > psu["watts"]:
            w.append(
                f"최대 부하 {peak:.0f}W 가 PSU 1개 용량({psu['watts']}W)을 초과합니다. "
                "PSU 1개 장애 시 리던던시(1+1)가 유지되지 않고 스로틀링/전원 차단 가능성이 있습니다."
            )
        elif peak > psu["watts"] * psu["count"]:
            w.append(f"최대 부하 {peak:.0f}W 가 전체 PSU 용량을 초과합니다.")
        elif psu["count"] >= 2 and peak > psu["watts"] * 0.9:
            w.append(f"최대 부하 {peak:.0f}W 가 PSU 1개 용량의 90%를 넘습니다. 여유가 부족합니다.")
    if cfg.unrecognized:
        w.append(f"분류하지 못한 항목 {len(cfg.unrecognized)}개는 계산에서 제외했습니다.")
    return w
