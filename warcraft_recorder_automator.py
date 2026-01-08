# file: warcraft_recorder_automator.py

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
import time

def add_email_to_roster(login_email, login_password, new_user_email):
    """
    Logs into warcraftrecorder.com and adds a new email to the roster.
    Returns True on success, or the error string on failure.
    """
    print("Starting Playwright browser...")
    
    with sync_playwright() as p:
        try:
            # Launch Chromium in headless mode
            browser = p.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-gpu'
                ]
            )
            
            context = browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            page = context.new_page()
            page.set_default_timeout(20000)  # 20 second timeout
            
            print("✅ Browser initialized successfully")

            # Navigate to the website
            print("Navigating to the website...")
            page.goto("https://warcraftrecorder.com/")
            
            # Click the first login button
            print("Finding and clicking the first login button...")
            page.click("button:has-text('Login')")
            
            # Wait for and fill in login form
            print("Waiting for login form...")
            page.wait_for_selector('input[name="user"]', state='visible')
            print("Entering credentials...")
            page.fill('input[name="user"]', login_email)
            page.fill('input[name="pass"]', login_password)
            
            # Submit login
            print("Finding and clicking the final submit button...")
            page.click('button[type="submit"]')
            print("Login complete!")
            
            # Navigate to Guild Administration
            print("Waiting for 'Guild Administration' button...")
            page.click("button:has(h2:text('Guild Administration'))")
            print("Clicked 'Guild Administration'.")
            
            # Click Add User in menu
            print("Waiting for 'Add User' button in menu...")
            page.click("button:text('Add User')")
            print("Clicked 'Add User' button.")
            
            # Fill in the new user email
            print("Waiting for 'Add User' dialog to appear...")
            page.wait_for_selector('#userEmail', state='visible')
            print("Entering new user's email...")
            page.fill('#userEmail', new_user_email)
            
            # Submit the add user form
            print("Finding and clicking the final 'Add User' button in the dialog...")
            page.click("div[role='dialog'] button:text('Add User')")
            print("Submitted new user. Now checking for toast notification...")
            
            # Wait for toast notification
            try:
                toast = page.wait_for_selector("li[role='status']", state='visible', timeout=10000)
                
                # Check if it's an error toast
                toast_class = toast.get_attribute('class') or ''
                if 'destructive' in toast_class:
                    error_div = toast.query_selector("div[class*='opacity-90']")
                    error_text = error_div.inner_text() if error_div else "Unknown error"
                    print(f"❌ Failure toast detected: {error_text}")
                    return error_text
                else:
                    # Success toast
                    success_div = toast.query_selector("div[class*='opacity-90']")
                    success_text = success_div.inner_text() if success_div else "Success"
                    print(f"✅ Success toast detected: {success_text}")
                    return True
                    
            except PlaywrightTimeout:
                print("⚠️ No toast notification was detected. Assuming failure for safety.")
                return "No confirmation toast was found after submitting."
                
        except PlaywrightTimeout as e:
            print(f"❌ Timeout error: {e}")
            # Save screenshot for debugging
            try:
                page.screenshot(path='/tmp/debug_screenshot.png')
                print("Debug screenshot saved to /tmp/debug_screenshot.png")
            except:
                pass
            return f"Timeout error during automation: {str(e)}"
            
        except Exception as e:
            print(f"❌ An unexpected error occurred: {e}")
            try:
                page.screenshot(path='/tmp/debug_screenshot.png')
                print("Debug screenshot saved to /tmp/debug_screenshot.png")
            except:
                pass
            return f"An unexpected script error occurred: {str(e)}"
            
        finally:
            print("Closing the browser.")
            try:
                browser.close()
            except:
                pass

    # Add this entire block to the END of your warcraft_recorder_automator.py file