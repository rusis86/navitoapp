# EIPT 연동 작업 메모

목표: 사용자의 Dell 계정으로 Dell EIPT(https://powercalculator.dell.com)에 로그인해,
서비스태그 구성으로 EIPT 공식 전력값(프로파일별)을 조회해 앱에 표시.

## 완료
- `dellpower/eipt.py`: Playwright 로그인 자동화 (이메일 → #btnContinue → 비밀번호 → #btnSignIn, OTP 감지)
  - 가짜 계정으로 검증: Dell 오류 메시지("unable to match the details...")까지 정상 수신
- `scripts/eipt_explore.py`: 로그인 후 EIPT 화면/링크/XHR 요청 수집

## 다음 단계
1. 환경변수 `DELL_EIPT_USER`, `DELL_EIPT_PASSWORD` 가 설정된 세션에서
   `python scripts/eipt_explore.py <scratchpad>/eipt_out` 실행
   - OTP 요구 시 종료코드 2 → 사용자에게 코드 받는 흐름 필요
2. 수집 결과로 EIPT 구성 입력 방식 파악 (서비스태그 import 기능 유무, 혹은 XHR API 직접 호출 가능 여부)
3. 서비스태그 → 구성(기존 dell_api / 직접 입력) → EIPT 입력 → 결과(Idle/Max/Typical W, 프로파일) 파싱
4. 앱 UI에 "EIPT 계정" 입력란 (저장하지 않음) + EIPT 결과와 자체 추정값 비교 표시

## 네트워크
환경 Network access에 `*.dell.com`, `*.dellcdn.com` 허용 필요 (로그인은 www.dell.com 경유).
