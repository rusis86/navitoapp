# Dell PowerEdge 전력 계산기

Dell 서비스태그를 입력하면 출하 구성(CPU/메모리/드라이브/NIC/GPU/PSU 등)을 조회해
BIOS 시스템 프로파일별 소비전력을 추정합니다.

| 프로파일 | BIOS 설정 | 특징 |
|---|---|---|
| 퍼포먼스 | System Profile = Performance | C-State off, Turbo on → 유휴 전력 최고 |
| 밸런스 | Performance Per Watt (DAPC) | Dell 기본값, 부하 비례 |
| 저전력 | Custom: Turbo off, C-State on, EEP=Power, 메모리 주파수 하향 | 최대 전력 약 15~20% 절감 |

출력: 유휴/일반/최대 AC 전력(W), 발열(BTU/h), 전류(A), 연간 kWh·전기요금, 부품별 DC 분해,
PSU 리던던시(1+1) 경고, iDRAC Power Cap 적용, CSV 다운로드.

## 실행

```bash
pip install -r requirements.txt
cp .env.example .env   # Dell TechDirect API 키 입력 (선택)
export $(grep -v '^#' .env | xargs)
uvicorn dellpower.main:app --host 0.0.0.0 --port 8000
```

브라우저에서 `http://<host>:8000` 접속. API 키가 없어도 데모 태그
(`DEMO740`, `DEMO760`, `DEMO7625`, `DEMOXE`)와 **구성 직접 입력** 탭으로 사용할 수 있습니다.

## Dell API

[Dell TechDirect](https://tdm.dell.com)에서 Warranty/Asset API 키(client_id/secret)를 발급받아 사용합니다.

- `POST /auth/oauth/v2/token` (client_credentials)
- `GET /PROD/sbil/eapi/v5/asset-components?servicetag=XXXX`

## REST API

- `GET /api/servicetag/{tag}?utilization=0.5&kwh_rate=180&pue=1.0&voltage=220&power_cap=`
- `POST /api/estimate` — `{"model":"PowerEdge R760","text":"2 x Intel Xeon Gold 6430 (270W)\n16 x 64GB RDIMM, 4800MT/s","options":{...}}`

## 계산 모델

- 부품별 (idle, max) 전력 → `P(u) = idle + (max-idle)·u^curve`
- CPU: 설명의 TDP `(270W)` 우선, 없으면 내장 카탈로그(Xeon E5 v3 ~ Xeon 6, EPYC 7002 ~ 9005), 그래도 없으면 코어 수 기반 추정
- 팬: 폼팩터(1U/2U/4U/6U/타워)와 프로파일 최소 팬 속도, GPU·고성능 팬 장착 시 상향
- PSU: 80 PLUS 효율 곡선(Titanium/Platinum/Gold)으로 DC → AC 환산, 부하 분담 가정

> 추정치입니다. 최종 설계는 Dell EIPT 또는 iDRAC 실측(전력 모니터링)으로 검증하세요.
> 수치 보정은 `dellpower/catalog.py`, 프로파일 계수는 `dellpower/estimator.py`의 `PROFILES`에서 조정합니다.

## 테스트

```bash
python -m pytest -q
```
