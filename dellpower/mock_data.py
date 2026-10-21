"""API 키 없이 테스트할 수 있는 데모 서비스태그 (Asset Components 응답 형식)."""


def _c(desc: str, qty: int = 1, sku: str | None = None) -> dict:
    return {"itemNumber": sku or desc[:20], "itemDescription": desc,
            "partNumber": "", "partQuantity": qty}


DEMO_ASSETS = {
    "DEMO740": {
        "serviceTag": "DEMO740", "systemDescription": "PowerEdge R740",
        "shipDate": "2020-06-15T00:00:00Z", "countryCode": "KR",
        "components": [
            _c("PowerEdge R740 Motherboard", 1),
            _c("Intel Xeon Gold 6248 2.5G, 20C/40T, 10.4GT/s, 27.5M Cache, Turbo, HT (150W) DDR4-2933", 2),
            _c("32GB RDIMM, 2933MT/s, Dual Rank", 12),
            _c("PERC H740P RAID Controller, 8GB NV Cache, Minicard", 1),
            _c("1.92TB SSD SATA Read Intensive 6Gbps 512 2.5in Hot-plug AG Drive", 4),
            _c("2.4TB 10K RPM SAS 12Gbps 512e 2.5in Hot-plug Hard Drive", 6),
            _c("BOSS controller card + with 2 M.2 Sticks 240G (RAID 1),FH", 1),
            _c("Broadcom 57416 2 Port 10Gb Base-T + 5720 2 Port 1Gb Base-T, rNDC", 1),
            _c("Mellanox ConnectX-4 Lx Dual Port 25GbE SFP28 Network Adapter, Full Height", 1),
            _c("Dual, Hot-plug, Redundant Power Supply (1+1), 750W", 1),
            _c("6 Standard Fans for R740/740XD", 1),
            _c("iDRAC9,Enterprise", 1),
            _c("ReadyRails Sliding Rails With Cable Management Arm", 1),
        ],
    },
    "DEMO760": {
        "serviceTag": "DEMO760", "systemDescription": "PowerEdge R760",
        "shipDate": "2024-03-02T00:00:00Z", "countryCode": "KR",
        "components": [
            _c("Intel Xeon Gold 6430 2.1G, 32C/64T, 16GT/s, 60M Cache, Turbo, HT (270W) DDR5-4400", 2),
            _c("64GB RDIMM, 4800MT/s Dual Rank", 16),
            _c("PERC H755 SAS Front", 1),
            _c("3.84TB Data Center NVMe Read Intensive AG Drive U2 Gen4 with carrier", 8),
            _c("BOSS-N1 controller card + with 2 M.2 480GB (RAID 1)", 1),
            _c("Broadcom 57504 Quad Port 10/25GbE,SFP28, OCP NIC 3.0", 1),
            _c("Nvidia ConnectX-6 Lx Dual Port 10/25GbE SFP28 Adapter, PCIe Full Height", 1),
            _c("Dual, Fully Redundant(1+1), Hot-Plug Power Supply, 1400W MM (100-240Vac) Titanium", 1),
            _c("High Performance Gold Fan x6", 1),
            _c("Windows Server 2022 Standard,16CORE", 1),
        ],
    },
    "DEMO7625": {
        "serviceTag": "DEMO7625", "systemDescription": "PowerEdge R7625",
        "shipDate": "2024-09-10T00:00:00Z", "countryCode": "KR",
        "components": [
            _c("AMD EPYC 9354 3.25GHz, 32C/64T, 256M Cache (280W) DDR5-4800", 2),
            _c("32GB RDIMM, 4800MT/s Single Rank", 24),
            _c("PERC H965i Front", 1),
            _c("7.68TB Data Center NVMe Read Intensive AG Drive U2 Gen4", 4),
            _c("16TB Hard Drive SAS ISE 12Gbps 7.2K 512e 3.5in Hot-Plug", 8),
            _c("Broadcom 57414 Dual Port 10/25GbE SFP28, OCP NIC 3.0", 1),
            _c("Emulex LPe35002 Dual Port FC32 Fibre Channel HBA, PCIe Full Height", 1),
            _c("Dual, Fully Redundant (1+1), Hot-Plug Power Supply, 1100W MM (100-240Vac) Titanium", 1),
        ],
    },
    "DEMOXE": {
        "serviceTag": "DEMOXE", "systemDescription": "PowerEdge R760xa",
        "shipDate": "2024-11-20T00:00:00Z", "countryCode": "KR",
        "components": [
            _c("Intel Xeon Platinum 8462Y+ 2.8G, 32C/64T, 16GT/s, 60M Cache, Turbo, HT (300W) DDR5-4800", 2),
            _c("64GB RDIMM, 4800MT/s Dual Rank", 16),
            _c("NVIDIA L40S 48GB PCIe Gen4 Passive GPU", 4),
            _c("1.92TB Data Center NVMe Mixed Use AG Drive U2 Gen4", 2),
            _c("BOSS-N1 controller card + with 2 M.2 960GB (RAID 1)", 1),
            _c("Nvidia ConnectX-7 Single Port NDR200 OSFP PCIe 5.0 x16 200GbE Adapter", 2),
            _c("Dual, Fault Tolerant Redundant (1+1), Hot-Plug Power Supply, 2800W Titanium", 1),
        ],
    },
}
