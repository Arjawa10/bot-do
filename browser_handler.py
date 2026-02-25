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
            chrome_options.add_argument("--single-process")
            chrome_options.add_argument("--remote-debugging-pipe")
            chrome_options.add_argument("--window-size=1920,1080")

            # Heroku sets GOOGLE_CHROME_BIN / GOOGLE_CHROME_SHIM and CHROMEDRIVER_PATH
            chrome_bin = os.environ.get("GOOGLE_CHROME_SHIM") or os.environ.get("GOOGLE_CHROME_BIN")
            chromedriver_path = os.environ.get("CHROMEDRIVER_PATH")

            if chrome_bin:
                chrome_options.binary_location = chrome_bin

            if chromedriver_path:
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
            print(f"[LOGIN] Navigated to {LOGIN_URL}")

            wait = WebDriverWait(driver, 15)

            # Fill email
            email_field = await asyncio.to_thread(
                wait.until, EC.visibility_of_element_located((By.CSS_SELECTOR, "input[type='email'], input[name='email']"))
            )
            await asyncio.to_thread(email_field.clear)
            await asyncio.to_thread(email_field.send_keys, email)

            # Fill password
            password_field = await asyncio.to_thread(
                wait.until, EC.visibility_of_element_located((By.CSS_SELECTOR, "input[type='password'], input[name='password']"))
            )
            await asyncio.to_thread(password_field.clear)
            await asyncio.to_thread(password_field.send_keys, password)

            # Click login / submit button
            submit_btn = await asyncio.to_thread(
                wait.until, EC.element_to_be_clickable((By.CSS_SELECTOR, "button[type='submit']"))
            )
            await asyncio.to_thread(submit_btn.click)
            print("[LOGIN] Credentials submitted, waiting for response...")

            # Wait a moment for page to react
            await asyncio.sleep(5)

            # Check if OTP field appeared
            try:
                otp_field = await asyncio.to_thread(
                    lambda: WebDriverWait(driver, 10).until(
                        EC.visibility_of_element_located(
                            (By.CSS_SELECTOR, "input[name='otp'], input[type='tel'], input[name='code']")
                        )
                    )
                )
                print("[LOGIN] OTP field detected.")
                return "OTP_REQUIRED"
            except Exception:
                # No OTP field — check if we're logged in
                current_url = driver.current_url
                if "login" not in current_url.lower():
                    print("[LOGIN] Login successful (no OTP).")
                    return "LOGIN_SUCCESS"
                else:
                    # Still on login page — look for error messages
                    try:
                        error_el = driver.find_element(By.CSS_SELECTOR, ".error, .alert-danger, [role='alert']")
                        return f"LOGIN_FAILED: {error_el.text}"
                    except Exception:
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
            if self._driver is None:
                return "OTP_FAILED: Browser not started."

            driver = self._driver
            wait = WebDriverWait(driver, 10)

            # Find and fill OTP field
            otp_field = await asyncio.to_thread(
                wait.until, EC.visibility_of_element_located(
                    (By.CSS_SELECTOR, "input[name='otp'], input[type='tel'], input[name='code']")
                )
            )
            await asyncio.to_thread(otp_field.clear)
            await asyncio.to_thread(otp_field.send_keys, otp_code)

            # Click submit / verify button
            try:
                verify_btn = await asyncio.to_thread(
                    wait.until, EC.element_to_be_clickable((By.CSS_SELECTOR, "button[type='submit']"))
                )
                await asyncio.to_thread(verify_btn.click)
            except Exception:
                pass

            print("[OTP] OTP submitted, waiting for navigation...")
            await asyncio.sleep(5)

            current_url = driver.current_url
            if "login" not in current_url.lower():
                print("[OTP] Login successful after OTP.")
                return "LOGIN_SUCCESS"
            else:
                try:
                    error_el = driver.find_element(By.CSS_SELECTOR, ".error, .alert-danger, [role='alert']")
                    return f"OTP_FAILED: {error_el.text}"
                except Exception:
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
            if self._driver is None:
                return {
                    "available": False,
                    "message": "Browser not started.",
                    "timestamp": timestamp,
                    "current_url": "",
                }

            driver = self._driver

            # Navigate to GPU listing page
            await asyncio.to_thread(driver.get, GPU_PAGE_URL)
            print(f"[GPU CHECK] Navigated to {GPU_PAGE_URL}")
            await asyncio.sleep(3)

            # Try to click "Create a GPU Droplet" button
            try:
                wait = WebDriverWait(driver, 15)
                create_btn = await asyncio.to_thread(
                    wait.until, EC.element_to_be_clickable(
                        (By.XPATH, "//button[contains(text(), 'Create a GPU Droplet')] | //a[contains(text(), 'Create a GPU Droplet')]")
                    )
                )
                await asyncio.to_thread(create_btn.click)
                print("[GPU CHECK] Clicked 'Create a GPU Droplet' button.")
                await asyncio.sleep(3)
            except Exception:
                print("[GPU CHECK] 'Create a GPU Droplet' element not found, continuing check...")

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
