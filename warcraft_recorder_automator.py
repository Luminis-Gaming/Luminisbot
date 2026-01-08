# file: warcraft_recorder_automator.py

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
import time
import os

# Replace your entire function with this final version

def add_email_to_roster(login_email, login_password, new_user_email):
    """
    Logs into warcraftrecorder.com and adds a new email to the roster.
    Returns True on success, or the error string on failure.
    """
    driver = None
    
    try:
        # Use undetected_chromedriver for better stability
        options = uc.ChromeOptions()
        
        # Essential arguments for headless Docker environment
        options.add_argument('--headless=new')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--disable-setuid-sandbox')
        options.add_argument('--window-size=1920,1080')
        
        print("Initializing Chrome browser...")
        
        # Initialize with undetected_chromedriver
        driver = uc.Chrome(
            options=options,
            version_main=None,  # Auto-detect Chrome version
            headless=True,
            use_subprocess=True,
            log_level=3
        )
        
        wait = WebDriverWait(driver, 20)
        print("✅ Chrome initialized successfully")
        
    except Exception as e:
        print(f"❌ Failed to initialize Chrome: {e}")
        if driver:
            try:
                driver.quit()
            except:
                pass
        return f"Failed to start Chrome browser: {str(e)}"

    try:
        # 1-8: THE FULL LOGIN AND NAVIGATION PROCESS (No changes here)
        print("Navigating to the website...")
        driver.get("https://warcraftrecorder.com/")
        print("Finding and clicking the first login button...")
        login_button_homepage = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Login')]")))
        login_button_homepage.click()
        print("Waiting for login form...")
        email_field = wait.until(EC.visibility_of_element_located((By.NAME, "user")))
        password_field = driver.find_element(By.NAME, "pass")
        print("Entering credentials...")
        email_field.send_keys(login_email)
        password_field.send_keys(login_password)
        print("Finding and clicking the final submit button...")
        submit_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[@type='submit']")))
        submit_button.click()
        print("Login complete!")
        print("Waiting for 'Guild Administration' button...")
        guild_admin_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[h2[text()='Guild Administration']]")))
        guild_admin_button.click()
        print("Clicked 'Guild Administration'.")
        print("Waiting for 'Add User' button in menu...")
        add_user_menu_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[text()='Add User']")))
        add_user_menu_button.click()
        print("Clicked 'Add User' button.")
        print("Waiting for 'Add User' dialog to appear...")
        add_user_email_field = wait.until(EC.visibility_of_element_located((By.ID, "userEmail")))
        print("Entering new user's email...")
        add_user_email_field.send_keys(new_user_email)
        print("Finding and clicking the final 'Add User' button in the dialog...")
        final_add_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//div[@role='dialog']//button[text()='Add User']")))
        final_add_button.click()
        print("Submitted new user. Now checking for toast notification...")

        # 9: WAIT FOR ANY TOAST AND CHECK ITS TYPE
        try:
            # Wait for any toast (the <li> element) to become visible
            toast_xpath = "//li[@role='status']"
            toast_element = wait.until(EC.visibility_of_element_located((By.XPATH, toast_xpath)))
            
            # Check if it's an error toast by looking for the 'destructive' class
            if 'destructive' in toast_element.get_attribute('class'):
                error_message_div = toast_element.find_element(By.XPATH, ".//div[contains(@class, 'opacity-90')]")
                error_text = error_message_div.text
                print(f"❌ Failure toast detected: {error_text}")
                return error_text
            else:
                # If it's not a destructive toast, it's a success
                success_message_div = toast_element.find_element(By.XPATH, ".//div[contains(@class, 'opacity-90')]")
                print(f"✅ Success toast detected: {success_message_div.text}")
                return True

        except TimeoutException:
            # This is a fallback in case NO toast appears for some reason.
            print("⚠️ No toast notification was detected. Assuming failure for safety.")
            return "No confirmation toast was found after submitting."

    except Exception as e:
        print(f"❌ An unexpected error occurred: {e}")
        driver.save_screenshot('debug_screenshot.png')
        return f"An unexpected script error occurred. Check logs."
        
    finally:
        print("Closing the browser.")
        driver.quit()

    # Add this entire block to the END of your warcraft_recorder_automator.py file