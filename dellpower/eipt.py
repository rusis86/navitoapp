"""Dell EIPT (powercalculator.dell.com) 브라우저 자동화.

로그인 흐름 (2026-10 확인):
  powercalculator.dell.com -> www.dell.com/di/idp/dwa/authorize (Dell 계정 로그인)
  1) 이메일  #SignInModel_EmailAddress  -> #btnContinue
  2) 비밀번호 #userPwd_UserInputSecret  -> #btnSignIn
  3) (경우에 따라) 일회용 인증코드(OTP) 입력
  4) powercalculator.dell.com/Account/Callback 로 복귀

ID/PW 는 호출 시 인자로만 받고 디스크/로그에 남기지 않는다.
로그인 후 쿠키(storage_state)는 메모리에만 보관해 재사용한다.
"""
from __future__ import annotations

import os
from urllib.parse import urlparse
from dataclasses import dataclass

EIPT_URL = "https://powercalculator.dell.com/Build/System?productId=1"
EIPT_HOST = "powercalculator.dell.com"

SEL_EMAIL = "#SignInModel_EmailAddress"
SEL_EMAIL_CONTINUE = "#btnContinue:visible, #btnSSoContinue:visible"
SEL_PASSWORD = "#userPwd_UserInputSecret"
SEL_SIGNIN = "#btnSignIn"
SEL_OTP = "input[autocomplete='one-time-code'], input[name*='otp' i], input[id*='otp' i], input[name*='Code' i]"
COOKIE_BUTTONS = ("Decline All", "Accept All")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")


class EiptError(Exception):
    pass


class OtpRequired(EiptError):
    """Dell 이 일회용 인증코드를 요구함. 코드를 받아 submit_otp() 로 이어서 진행."""


@dataclass
class LoginResult:
    ok: bool
    url: str
    message: str = ""


def _chromium_path() -> str | None:
    p = os.getenv("CHROMIUM_PATH") or "/opt/pw-browsers/chromium"
    return p if os.path.exists(p) else None


class EiptSession:
    """Playwright 기반 EIPT 세션. with 문으로 사용."""

    def __init__(self, headless: bool = True, timeout_ms: int = 45000):
        self.headless = headless
        self.timeout_ms = timeout_ms
        self._pw = self._browser = self._ctx = self.page = None

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=self.headless, executable_path=_chromium_path(),
            args=["--disable-blink-features=AutomationControlled"])
        self._ctx = self._browser.new_context(
            user_agent=UA, viewport={"width": 1440, "height": 900}, locale="en-US")
        self._ctx.set_default_timeout(self.timeout_ms)
        self.page = self._ctx.new_page()
        return self

    def __exit__(self, *exc):
        for obj in (self._ctx, self._browser):
            try:
                obj and obj.close()
            except Exception:
                pass
        if self._pw:
            self._pw.stop()

    # -- helpers -----------------------------------------------------------
    def _dismiss_cookies(self):
        for label in COOKIE_BUTTONS:
            try:
                self.page.click(f"button:has-text('{label}')", timeout=1500)
                return
            except Exception:
                continue

    def _on_eipt(self) -> bool:
        u = urlparse(self.page.url)
        return u.hostname == EIPT_HOST and not u.path.startswith("/Account/")

    def _error_text(self) -> str:
        for sel in (".dds__message-bar", "[role=alert]", ".mdc-text-field-helper-text--validation-msg",
                    ".field-validation-error"):
            try:
                for el in self.page.query_selector_all(sel):
                    if el.is_visible():
                        t = el.inner_text().strip()
                        if t:
                            return t
            except Exception:
                pass
        return ""

    # -- login -------------------------------------------------------------
    def login(self, email: str, password: str) -> LoginResult:
        pg = self.page
        pg.goto(EIPT_URL, wait_until="domcontentloaded")
        try:
            pg.wait_for_selector(SEL_EMAIL, state="visible", timeout=20000)
        except Exception:
            pass
        if self._on_eipt():
            return LoginResult(True, pg.url, "이미 로그인됨")
        self._dismiss_cookies()

        pg.fill(SEL_EMAIL, email)
        pg.click(SEL_EMAIL_CONTINUE)
        try:
            pg.wait_for_selector(SEL_PASSWORD, state="visible", timeout=20000)
        except Exception:
            raise EiptError(f"비밀번호 단계로 넘어가지 못했습니다. {self._error_text()}".strip())

        pg.fill(SEL_PASSWORD, password)
        pg.click(SEL_SIGNIN)
        return self._wait_after_signin()

    def _wait_after_signin(self) -> LoginResult:
        pg = self.page
        for _ in range(int(self.timeout_ms / 1000)):
            pg.wait_for_timeout(1000)
            if self._on_eipt():
                pg.wait_for_load_state("load")
                pg.wait_for_timeout(2000)
                return LoginResult(True, pg.url, "로그인 성공")
            try:
                if pg.query_selector(SEL_OTP) and pg.is_visible(SEL_OTP):
                    raise OtpRequired("Dell 이 인증코드(OTP)를 요구합니다. 메일/문자로 받은 코드를 입력하세요.")
            except OtpRequired:
                raise
            except Exception:
                pass
            err = self._error_text()
            if err and "password" in err.lower():
                raise EiptError(f"로그인 실패: {err}")
        raise EiptError(f"로그인 후 EIPT 로 돌아오지 않았습니다. 현재 URL: {pg.url[:120]} {self._error_text()}")

    def submit_otp(self, code: str) -> LoginResult:
        self.page.fill(SEL_OTP, code)
        for label in ("Verify", "Continue", "Submit", "Sign In"):
            try:
                self.page.click(f"button:has-text('{label}'), input[value='{label}']", timeout=2000)
                break
            except Exception:
                continue
        return self._wait_after_signin()

    def storage_state(self) -> dict:
        return self._ctx.storage_state()
