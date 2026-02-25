import asyncio
from datetime import datetime
from playwright.async_api import async_playwright, Browser, Page, Playwright
from config import GPU_PAGE_URL, LOGIN_URL, OUT_OF_STOCK_TEXT


class BrowserHandler:
    """Handles all Playwright browser automation for DigitalOcean AMD GPU checking."""

    def __init__(self):
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._page: Page | None = None

    # ------------------------------------------------------------------
    # 1. Start Browser
    # ------------------------------------------------------------------
    async def start_browser(self) -> str:
        """Launch a Chromium browser instance (headed)."""
        try:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=False)
            context = await self._browser.new_context()
            self._page = await context.new_page()
            print("[BROWSER] Browser launched successfully.")
            return "Browser started successfully."
        except Exception as e:
            error_msg = f"Failed to start browser: {e}"
            print(f"[BROWSER ERROR] {error_msg}")
            return error_msg

    # ------------------------------------------------------------------
    # 2. Login
    # ------------------------------------------------------------------
    async def login(self, email: str, password: str) -> str:
        """
        Navigate to login page, fill credentials and submit.
        Returns:
            "OTP_REQUIRED"  – if OTP field appears after submission
            "LOGIN_SUCCESS" – if login succeeds without OTP
            "LOGIN_FAILED: <reason>" – on failure
        """
        try:
            if self._page is None:
                return "LOGIN_FAILED: Browser not started. Call start_browser() first."

            page = self._page

            # Navigate to login page
            await page.goto(LOGIN_URL, wait_until="networkidle")
            print(f"[LOGIN] Navigated to {LOGIN_URL}")

            # Fill email
            email_field = page.get_by_label("Email")
            await email_field.wait_for(state="visible", timeout=15000)
            await email_field.fill(email)

            # Fill password
            password_field = page.get_by_label("Password")
            await password_field.fill(password)

            # Click login / submit button
            submit_btn = page.get_by_role("button", name="Log In")
            await submit_btn.click()
            print("[LOGIN] Credentials submitted, waiting for response...")

            # Wait for either OTP field or successful navigation
            try:
                # Wait up to 15 s for either OTP input or URL change indicating success
                otp_locator = page.locator("input[name='otp'], input[type='tel'], input[name='code']")
                await otp_locator.first.wait_for(state="visible", timeout=15000)
                print("[LOGIN] OTP field detected.")
                return "OTP_REQUIRED"
            except Exception:
                # OTP field did not appear — check if we're logged in
                await page.wait_for_load_state("networkidle")
                current_url = page.url
                if "login" not in current_url.lower():
                    print("[LOGIN] Login successful (no OTP).")
                    return "LOGIN_SUCCESS"
                else:
                    # Still on login page — look for error messages
                    error_el = page.locator(".error, .alert-danger, [role='alert']")
                    if await error_el.count() > 0:
                        err_text = await error_el.first.inner_text()
                        return f"LOGIN_FAILED: {err_text}"
                    return "LOGIN_FAILED: Unknown error — still on login page."

        except Exception as e:
            error_msg = f"LOGIN_FAILED: {e}"
            print(f"[LOGIN ERROR] {error_msg}")
            return error_msg

    # ------------------------------------------------------------------
    # 3. Submit OTP
    # ------------------------------------------------------------------
    async def submit_otp(self, otp_code: str) -> str:
        """
        Fill and submit the OTP code on the current page.
        Returns:
            "LOGIN_SUCCESS" – if OTP succeeds
            "OTP_FAILED: <reason>" – on failure
        """
        try:
            if self._page is None:
                return "OTP_FAILED: Browser not started."

            page = self._page

            # Find and fill OTP field
            otp_field = page.locator("input[name='otp'], input[type='tel'], input[name='code']")
            await otp_field.first.wait_for(state="visible", timeout=10000)
            await otp_field.first.fill(otp_code)

            # Click submit / verify button
            verify_btn = page.get_by_role("button", name="Verify")
            if await verify_btn.count() == 0:
                # Fallback: try any submit button
                verify_btn = page.locator("button[type='submit']")
            await verify_btn.first.click()

            print("[OTP] OTP submitted, waiting for navigation...")
            await page.wait_for_load_state("networkidle")

            current_url = page.url
            if "login" not in current_url.lower():
                print("[OTP] Login successful after OTP.")
                return "LOGIN_SUCCESS"
            else:
                error_el = page.locator(".error, .alert-danger, [role='alert']")
                if await error_el.count() > 0:
                    err_text = await error_el.first.inner_text()
                    return f"OTP_FAILED: {err_text}"
                return "OTP_FAILED: Unknown error — still on login page."

        except Exception as e:
            error_msg = f"OTP_FAILED: {e}"
            print(f"[OTP ERROR] {error_msg}")
            return error_msg

    # ------------------------------------------------------------------
    # 4. Check GPU Availability
    # ------------------------------------------------------------------
    async def check_gpu_availability(self) -> dict:
        """
        Navigate to GPU page, click 'Create a GPU Droplet', and check stock.
        Returns a dict with keys: available, message, timestamp, current_url.
        """
        timestamp = datetime.now().strftime("%d-%m-%Y %H:%M:%S")

        try:
            if self._page is None:
                return {
                    "available": False,
                    "message": "Browser not started.",
                    "timestamp": timestamp,
                    "current_url": "",
                }

            page = self._page

            # Navigate to GPU listing page (same tab)
            await page.goto(GPU_PAGE_URL, wait_until="networkidle")
            print(f"[GPU CHECK] Navigated to {GPU_PAGE_URL}")

            # Click "Create a GPU Droplet" button
            create_btn = page.get_by_role("button", name="Create a GPU Droplet")
            try:
                await create_btn.wait_for(state="visible", timeout=15000)
                await create_btn.click()
                print("[GPU CHECK] Clicked 'Create a GPU Droplet' button.")
            except Exception:
                # Button might be a link instead
                create_link = page.get_by_role("link", name="Create a GPU Droplet")
                try:
                    await create_link.wait_for(state="visible", timeout=5000)
                    await create_link.click()
                    print("[GPU CHECK] Clicked 'Create a GPU Droplet' link.")
                except Exception:
                    print("[GPU CHECK] 'Create a GPU Droplet' element not found, continuing check...")

            # Wait for content to load
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(2)  # small extra wait for dynamic content

            # Check for out-of-stock text
            out_of_stock = page.get_by_text(OUT_OF_STOCK_TEXT)
            is_out_of_stock = await out_of_stock.count() > 0

            current_url = page.url

            if is_out_of_stock:
                return {
                    "available": False,
                    "message": OUT_OF_STOCK_TEXT,
                    "timestamp": timestamp,
                    "current_url": current_url,
                }
            else:
                return {
                    "available": True,
                    "message": "GPU appears to be available!",
                    "timestamp": timestamp,
                    "current_url": current_url,
                }

        except Exception as e:
            error_msg = f"Error checking GPU: {e}"
            print(f"[GPU CHECK ERROR] {error_msg}")
            return {
                "available": False,
                "message": error_msg,
                "timestamp": timestamp,
                "current_url": "",
            }

    # ------------------------------------------------------------------
    # 5. Close Browser
    # ------------------------------------------------------------------
    async def close_browser(self) -> None:
        """Shut down the browser and release all resources."""
        try:
            if self._browser:
                await self._browser.close()
                self._browser = None
                self._page = None
            if self._playwright:
                await self._playwright.stop()
                self._playwright = None
            print("[BROWSER] Browser closed.")
        except Exception as e:
            print(f"[BROWSER ERROR] Failed to close browser: {e}")
