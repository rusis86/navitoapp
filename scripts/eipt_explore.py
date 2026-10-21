"""EIPT 로그인 후 화면 구조 수집용 개발 스크립트.

환경변수 DELL_EIPT_USER / DELL_EIPT_PASSWORD 로 로그인한 뒤
주요 페이지의 스크린샷/HTML/네트워크(XHR) 요청 목록을 OUT 디렉터리에 저장한다.
비밀번호는 출력/저장하지 않는다.

  python scripts/eipt_explore.py /path/to/out
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dellpower.eipt import EiptSession, OtpRequired  # noqa: E402

out = sys.argv[1] if len(sys.argv) > 1 else "eipt_out"
os.makedirs(out, exist_ok=True)
user, pw = os.getenv("DELL_EIPT_USER"), os.getenv("DELL_EIPT_PASSWORD")
if not (user and pw):
    sys.exit("DELL_EIPT_USER / DELL_EIPT_PASSWORD 환경변수가 필요합니다.")

xhr = []
with EiptSession() as s:
    s.page.on("request", lambda r: r.resource_type in ("xhr", "fetch")
              and xhr.append({"method": r.method, "url": r.url, "post": (r.post_data or "")[:2000]}))
    try:
        res = s.login(user, pw)
        print("LOGIN:", res.message, res.url)
    except OtpRequired as e:
        print("OTP 필요:", e)
        s.page.screenshot(path=f"{out}/otp.png")
        sys.exit(2)
    s.page.screenshot(path=f"{out}/01_system.png", full_page=True)
    open(f"{out}/01_system.html", "w").write(s.page.content())
    links = s.page.eval_on_selector_all(
        "a[href]", "els=>els.map(e=>[e.innerText.trim().slice(0,60), e.href]).filter(x=>x[0])")
    json.dump(links, open(f"{out}/links.json", "w"), ensure_ascii=False, indent=1)
    json.dump(xhr, open(f"{out}/xhr.json", "w"), ensure_ascii=False, indent=1)
    print(f"saved to {out}: {len(links)} links, {len(xhr)} xhr")
