import pytest
from fastapi.testclient import TestClient

from dellpower.dell_api import lookup, normalize_asset
from dellpower.estimator import estimate
from dellpower.main import app
from dellpower.mock_data import DEMO_ASSETS
from dellpower.parser import build_config, classify, detect_form_factor, parse_text_config


@pytest.mark.parametrize("desc,cat", [
    ("Intel Xeon Gold 6430 2.1G, 32C/64T (270W) DDR5-4400", "cpu"),
    ("AMD EPYC 9354 3.25GHz, 32C/64T, 256M Cache (280W)", "cpu"),
    ("64GB RDIMM, 4800MT/s Dual Rank", "memory"),
    ("1.92TB SSD SATA Read Intensive 6Gbps 2.5in", "drive"),
    ("3.84TB NVMe Read Intensive U2 Gen4 with carrier", "drive"),
    ("PERC H755 SAS Front", "controller"),
    ("Nvidia ConnectX-6 Lx Dual Port 10/25GbE SFP28 Adapter", "nic"),
    ("NVIDIA L40S 48GB PCIe Gen4 Passive GPU", "gpu"),
    ("Dual, Hot-plug, Redundant Power Supply (1+1), 750W", "psu"),
    ("BOSS-N1 controller card + with 2 M.2 480GB", "boss"),
    ("iDRAC9,Enterprise", "ignore"),
    ("ReadyRails Sliding Rails With Cable Management Arm", "ignore"),
])
def test_classify(desc, cat):
    assert classify(desc) == cat


def test_cpu_tdp_from_catalog_when_missing_in_description():
    cfg = build_config("PowerEdge R650", [{"description": "Intel Xeon Gold 6338 2.0G, 32C/64T", "quantity": 2}])
    cpu = cfg.of("cpu")[0]
    assert cpu.attrs["tdp"] == 205 and cpu.attrs["tdp_source"] == "catalog"


@pytest.mark.parametrize("model,ff", [
    ("PowerEdge R650", "1U"), ("PowerEdge R760", "2U"), ("PowerEdge R7625", "2U"),
    ("PowerEdge T550", "TOWER"), ("PowerEdge XE9680", "6U"), ("PowerEdge R6615", "1U"),
])
def test_form_factor(model, ff):
    assert detect_form_factor(model) == ff


@pytest.mark.parametrize("tag", list(DEMO_ASSETS))
def test_profiles_order(tag):
    a = lookup(tag)
    r = estimate(build_config(a["model"], a["items"]))
    p = {x["key"]: x["points"] for x in r["profiles"]}
    d = r["default_profile"]["key"]
    # 유휴: 퍼포먼스 > 기본설정 > 저전력
    assert p["performance"]["idle"]["ac_watts"] > p[d]["idle"]["ac_watts"] > p["low_power"]["idle"]["ac_watts"]
    # 최대: 저전력이 가장 낮음
    assert p["low_power"]["max"]["ac_watts"] < p[d]["max"]["ac_watts"]
    for v in p.values():
        assert v["idle"]["ac_watts"] < v["typical"]["ac_watts"] < v["max"]["ac_watts"]
        assert v["max"]["ac_watts"] > v["max"]["dc_watts"]  # PSU 손실


def test_power_cap():
    a = lookup("DEMO760")
    r = estimate(build_config(a["model"], a["items"]), power_cap=800)
    for p in r["profiles"]:
        assert p["points"]["max"]["ac_watts"] <= 800
        assert p["points"]["max"]["capped"]


def test_psu_redundancy_warning():
    a = lookup("DEMO7625")
    r = estimate(build_config(a["model"], a["items"]))
    assert any("리던던시" in w for w in r["warnings"])


def test_normalize_counts_key_parts():
    data = {"systemDescription": "PowerEdge R750", "components": [
        {"itemNumber": "338-X", "itemDescription": "Intel Xeon Gold 6338 (205W)", "partNumber": "C1", "partDescription": "CLP,LKG,CPU", "partQuantity": 1},
        {"itemNumber": "338-X", "itemDescription": "Intel Xeon Gold 6338 (205W)", "partNumber": "P1", "partDescription": "PRC,6338,2.0,32C,205W", "partQuantity": 2},
    ]}
    n = normalize_asset(data)
    assert [(i["description"], i["quantity"]) for i in n["items"]] == [("Intel Xeon Gold 6338 (205W)", 2)]


def test_parse_text():
    items = parse_text_config("2 x Intel Xeon Gold 6430\n12, 64GB RDIMM, 4800MT/s\n# comment\nPERC H755")
    assert [i["quantity"] for i in items] == [2, 12, 1]


def test_api():
    c = TestClient(app)
    assert c.get("/").status_code == 200
    r = c.get("/api/servicetag/demo740?utilization=0.3")
    assert r.status_code == 200 and len(r.json()["profiles"]) == 4
    assert c.get("/api/servicetag/ZZZZZZZ").status_code == 400  # API 키 없음
    r = c.post("/api/estimate", json={"model": "PowerEdge R650", "text": "2 x Intel Xeon Gold 6338 (205W)\n16 x 32GB RDIMM, 3200MT/s"})
    assert r.status_code == 200


@pytest.mark.parametrize("tag,default,has_dapc", [
    ("DEMO760", "balanced", True),   # Intel -> PPW(DAPC)
    ("DEMO7625", "ppw_os", False),   # AMD   -> PPW(OS), DAPC 없음
])
def test_default_profile(tag, default, has_dapc):
    a = lookup(tag)
    r = estimate(build_config(a["model"], a["items"]))
    assert r["default_profile"]["key"] == default
    assert r["profiles"][0]["key"] == default and r["profiles"][0]["is_default"]
    assert r["profiles"][0]["vs_default"] == {"idle": 0, "typical": 0, "max": 0}
    assert r["default_profile"]["points"]["typical"] == r["profiles"][0]["points"]["typical"]["ac_watts"]
    assert ("balanced" in [x["key"] for x in r["profiles"]]) == has_dapc
    low = next(x for x in r["profiles"] if x["key"] == "low_power")
    assert low["vs_default"]["max"] < 0 and low["vs_default_cost"] < 0


# ---------------------------------------------------------------- dell.com CSV
from pathlib import Path  # noqa: E402

from dellpower.dell_config import parse_dell_csv  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "r760_order_ko.csv"


def _csv_cfg():
    parsed = parse_dell_csv(FIXTURE.read_text(encoding="utf-8-sig"), "B5VBTB4.csv")
    return parsed, build_config(parsed["model"], parsed["items"])


def test_csv_model_and_tag():
    parsed, cfg = _csv_cfg()
    assert parsed["model"] == "PowerEdge R760"
    assert parsed["service_tag"] == "B5VBTB4"
    assert cfg.form_factor == "2U"


def test_csv_quantities_from_key_parts():
    _, cfg = _csv_cfg()
    q = lambda cat: sum(c.quantity for c in cfg.of(cat))  # noqa: E731
    assert q("cpu") == 2 and cfg.of("cpu")[0].attrs["tdp"] == 195
    assert q("memory") == 12                       # 16GB DDR5 x12 (정보성 '5600MT/s RDIMMs' 제외)
    assert cfg.of("memory")[0].attrs["generation"] == "DDR5"
    assert q("drive") == 3                         # 960GB SATA x1 + 800GB SAS x2
    assert q("transceiver") == 8
    assert q("psu") == 2 and cfg.of("psu")[0].attrs["watts"] == 1400
    nics = {(c.attrs["type"], c.attrs["speed"]): c.quantity for c in cfg.of("nic")}
    assert nics[("ETH", 25)] == 4 and nics[("ETH", 1)] == 1
    assert sum(c.quantity for c in cfg.of("nic") if c.attrs["type"] == "FC") == 3
    assert [c.attrs["model"] for c in cfg.of("controller")] == ["H755"]
    assert not cfg.of("boss")                      # 'BOSS 블랭크' 는 부품 아님
    assert cfg.unrecognized == []


def test_csv_factory_performance_bios_is_default():
    _, cfg = _csv_cfg()
    assert cfg.factory_profile == "performance"    # 384-BBBL 성능 BIOS 설정
    r = estimate(cfg)
    assert r["default_profile"]["key"] == "performance"
    assert r["default_profile"]["source"] == "order"


def test_csv_api():
    c = TestClient(app)
    r = c.post("/api/estimate/csv", json={"csv": FIXTURE.read_text(encoding="utf-8-sig"), "filename": "B5VBTB4.csv"})
    assert r.status_code == 200
    body = r.json()
    assert body["model"] == "PowerEdge R760" and body["asset"]["service_tag"] == "B5VBTB4"
    assert c.post("/api/estimate/csv", json={"csv": ""}).status_code == 400


FIXTURE_7725 = Path(__file__).parent / "fixtures" / "r7725_gpu_order_ko.csv"


def test_csv_r7725_gpu():
    parsed = parse_dell_csv(FIXTURE_7725.read_text(encoding="utf-8-sig"), "8YHFVH4.csv")
    cfg = build_config(parsed["model"], parsed["items"])
    q = lambda cat: sum(c.quantity for c in cfg.of(cat))  # noqa: E731
    assert parsed["model"] == "PowerEdge R7725" and parsed["service_tag"] == "8YHFVH4"
    assert q("cpu") == 2 and cfg.of("cpu")[0].attrs["vendor"] == "AMD"
    assert q("gpu") == 2 and cfg.of("gpu")[0].attrs["tdp"] == 450   # 랙 서버 기준 450W (XE 600W 아님)
    assert q("boss") == 1                          # 캐리어/라벨 행은 세지 않음
    assert q("memory") == 16 and q("drive") == 4
    assert cfg.of("drive")[0].attrs["kind"] == "SSD_NVME_GEN5"
    assert q("transceiver") == 4 and q("psu") == 2
    assert cfg.of("fan")[0].attrs["tier"] == "VHP"  # 17G 플래티넘 팬
    assert cfg.unrecognized == []
    r = estimate(cfg)
    assert cfg.factory_profile == "power_saving"   # 384-BBBH 절전 BIOS 설정
    assert r["default_profile"]["key"] == "ppw_os" and r["default_profile"]["source"] == "order"
    assert "balanced" not in [p["key"] for p in r["profiles"]]   # AMD: DAPC 없음
