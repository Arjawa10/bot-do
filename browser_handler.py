import asyncio
import os
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from config import GPU_PAGE_URL, LOGIN_URL, OUT_OF_STOCK_TEXT


class BrowserHandler:
    """Handles all Selenium browser automation for DigitalOcean AMD GPU checking."""

    def __init__(self):
        self._driver: webdriver.Chrome | None = None

    # ------------------------------------------------------------------
    # 1. Start Browser
    # ------------------------------------------------------------------
    async def start_browser(self) -> str:
        """Launch a headless Chrome browser instance."""
        try:
            chrome_options = Options()
            chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--disable-extensions")
            chrome_options.add_argument("--disable-software-rasterizer")
            chrome_options.add_argument("--disable-background-networking")
            chrome_options.add_argument("--disable-default-apps")
            chrome_options.add_argument("--disable-setuid-sandbox")
            chrome_options.add_argument("--window-size=1920,1080")

            # Heroku sets GOOGLE_CHROME_BIN / GOOGLE_CHROME_SHIM and CHROMEDRIVER_PATH
            chrome_bin = os.environ.get("GOOGLE_CHROME_SHIM") or os.environ.get("GOOGLE_CHROME_BIN")
            chromedriver_path = os.environ.get("CHROMEDRIVER_PATH")

            if chrome_bin:
                chrome_options.binary_location = chrome_bin
                print(f"[BROWSER] Using Chrome binary: {chrome_bin}")

            if chromedriver_path:
                print(f"[BROWSER] Using ChromeDriver: {chromedriver_path}")
                service = Service(executable_path=chromedriver_path)
                self._driver = await asyncio.to_thread(
                    lambda: webdriver.Chrome(service=service, options=chrome_options)
                )
            else:
                self._driver = await asyncio.to_thread(
                    lambda: webdriver.Chrome(options=chrome_options)
                )

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
            if self._driver is None:
                return "LOGIN_FAILED: Browser not started. Call start_browser() first."

            driver = self._driver

            # Navigate to login page
            await asyncio.to_thread(driver.get, LOGIN_URL)
            await asyncio.sleep(3)
            print(f"[LOGIN] Navigated to {LOGIN_URL}")
            print(f"[LOGIN] Page title: {driver.title}")

            wait = WebDriverWait(driver, 20)

            # Fill email (id="email")
            email_field = await asyncio.to_thread(
                wait.until, EC.presence_of_element_located((By.ID, "email"))
            )
            await asyncio.sleep(1)
            await asyncio.to_thread(email_field.clear)
            await asyncio.to_thread(email_field.send_keys, email)
            print("[LOGIN] Email entered.")

            # Fill password (id="password")
            password_field = await asyncio.to_thread(
                wait.until, EC.presence_of_element_located((By.ID, "password"))
            )
            await asyncio.to_thread(password_field.clear)
            await asyncio.to_thread(password_field.send_keys, password)
            print("[LOGIN] Password entered.")

            # Click "Log In" button
            submit_btn = await asyncio.to_thread(
                wait.until, EC.element_to_be_clickable((By.CSS_SELECTOR, "button[type='submit']"))
            )
            await asyncio.to_thread(submit_btn.click)
            print("[LOGIN] Login button clicked, waiting for response...")

            # Wait for page to react (URL stays the same, content changes dynamically)
            await asyncio.sleep(5)

            # Check if OTP/verification field appeared (id="code")
            try:
                otp_field = await asyncio.to_thread(
                    lambda: WebDriverWait(driver, 15).until(
                        EC.presence_of_element_located((By.ID, "code"))
                    )
                )
                print("[LOGIN] OTP/verification code field detected (id=code).")
                return "OTP_REQUIRED"
            except Exception:
                pass

            # Check if we navigated away from login (success)
            current_url = driver.current_url
            page_source = driver.page_source
            print(f"[LOGIN] Current URL after login attempt: {current_url}")

            # Check for success indicators (redirects to /projects/ after login)
            if "projects" in current_url.lower() or "dashboard" in current_url.lower() or "gpus" in current_url.lower():
                print("[LOGIN] Login successful (no OTP).")
                return "LOGIN_SUCCESS"

            # Check for error messages on page
            try:
                error_el = driver.find_element(By.CSS_SELECTOR, ".error, .alert-danger, [role='alert'], .notice--error")
                err_text = error_el.text
                if err_text:
                    print(f"[LOGIN] Error found: {err_text}")
                    return f"LOGIN_FAILED: {err_text}"
            except Exception:
                pass

            # Check for "Verify" text in page (alternative OTP detection)
            if "verify" in page_source.lower() or "6-digit" in page_source.lower():
                print("[LOGIN] Verification page detected via page content.")
                return "OTP_REQUIRED"

            return "LOGIN_FAILED: Unknown error — page did not change as expected."

        except Exception as e:
            error_msg = f"LOGIN_FAILED: {e}"
            print(f"[LOGIN ERROR] {error_msg}")
            return error_msg

    # ------------------------------------------------------------------
    # 3. Submit OTP
    # ------------------------------------------------------------------
    async def submit_otp(self, otp_code: str) -> str:
        """
        Fill and submit the OTP/verification code on the current page.
        Returns:
            "LOGIN_SUCCESS" – if OTP succeeds
            "OTP_FAILED: <reason>" – on failure
        """
        try:
            if self._driver is None:
                return "OTP_FAILED: Browser not started."

            driver = self._driver
            wait = WebDriverWait(driver, 15)

            # Find and fill OTP field (id="code")
            otp_field = await asyncio.to_thread(
                wait.until, EC.presence_of_element_located((By.ID, "code"))
            )
            await asyncio.to_thread(otp_field.clear)
            await asyncio.to_thread(otp_field.send_keys, otp_code)
            print(f"[OTP] Code entered.")

            # Click "Verify Code" button
            try:
                verify_btn = await asyncio.to_thread(
                    wait.until, EC.element_to_be_clickable(
                        (By.XPATH, "//button[contains(text(), 'Verify')]")
                    )
                )
                await asyncio.to_thread(verify_btn.click)
                print("[OTP] Verify button clicked.")
            except Exception:
                # Fallback: try any submit button
                try:
                    submit_btn = await asyncio.to_thread(
                        wait.until, EC.element_to_be_clickable(
                            (By.CSS_SELECTOR, "button[type='submit']")
                        )
                    )
                    await asyncio.to_thread(submit_btn.click)
                    print("[OTP] Submit button clicked (fallback).")
                except Exception:
                    pass

            await asyncio.sleep(5)

            current_url = driver.current_url
            page_source = driver.page_source
            print(f"[OTP] Current URL: {current_url}")

            # Success if we left the login page or no more verify content
            if "login" not in current_url.lower():
                print("[OTP] Login successful after OTP.")
                return "LOGIN_SUCCESS"

            # Still on login URL but maybe content changed (redirected to /projects/)
            if "projects" in current_url.lower() or ("verify" not in page_source.lower() and "6-digit" not in page_source.lower()):
                print("[OTP] Login successful (verification screen gone).")
                return "LOGIN_SUCCESS"

            # Check for error
            try:
                error_el = driver.find_element(By.CSS_SELECTOR, ".error, .alert-danger, [role='alert'], .notice--error")
                err_text = error_el.text
                if err_text:
                    return f"OTP_FAILED: {err_text}"
            except Exception:
                pass

            return "OTP_FAILED: Unknown error — still on verification page."

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
            if self._driver is None:
                return {
                    "available": False,
                    "message": "Browser not started.",
                    "timestamp": timestamp,
                    "current_url": "",
                }

            driver = self._driver

            # Navigate directly to GPU creation page (/gpus/new)
            await asyncio.to_thread(driver.get, GPU_PAGE_URL)
            await asyncio.sleep(5)
            print(f"[GPU CHECK] Navigated to {GPU_PAGE_URL}")
            print(f"[GPU CHECK] Page title: {driver.title}")

            # Check for out-of-stock text
            page_source = driver.page_source
            current_url = driver.current_url

            if OUT_OF_STOCK_TEXT in page_source:
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
            if self._driver:
                await asyncio.to_thread(self._driver.quit)
                self._driver = None
            print("[BROWSER] Browser closed.")
        except Exception as e:
            print(f"[BROWSER ERROR] Failed to close browser: {e}")
