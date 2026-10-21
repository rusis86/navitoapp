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


def test_normalize_merges_duplicate_rows():
    data = {"systemDescription": "PowerEdge R750", "components": [
        {"itemNumber": "338-X", "itemDescription": "Intel Xeon Gold 6338 (205W)", "partNumber": "P1", "partQuantity": 1},
        {"itemNumber": "338-X", "itemDescription": "Intel Xeon Gold 6338 (205W)", "partNumber": "P1", "partQuantity": 1},
    ]}
    n = normalize_asset(data)
    assert n["items"] == [{"description": "Intel Xeon Gold 6338 (205W)", "quantity": 2, "sku": "338-X"}]


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
