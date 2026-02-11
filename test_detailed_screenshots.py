import asyncio
import os
from pathlib import Path
from playwright.async_api import async_playwright, expect


screenshot_counter = 0


async def take_screenshot(page, description):
    global screenshot_counter
    screenshot_counter += 1
    base_dir = Path("/home/robot/autofolio")
    filename = f"step_{screenshot_counter:02d}_{description.replace(' ', '_').lower()}.png"
    filepath = base_dir / filename
    await page.screenshot(path=str(filepath), full_page=True)
    print(f"   SCREENSHOT: {filename} - {description}")
    if filepath.exists():
        print(f"   ✓ Saved to: {filepath}")
    else:
        print(f"   ✗ File not found at: {filepath}")
    return filename


async def test_detailed_screenshots():
    test_portfolio = Path("/tmp/test-autofolio-portfolio")
    test_portfolio.mkdir(exist_ok=True)
    
    (test_portfolio / "README.md").write_text("# Test Portfolio\n\nA test portfolio.\n")
    (test_portfolio / "package.json").write_text('{"name": "test-portfolio", "version": "1.0.0"}')
    
    os.chdir(str(test_portfolio))
    os.system("git init 2>/dev/null")
    os.system("git config user.email 'test@test.com' 2>/dev/null")
    os.system("git config user.name 'Test User' 2>/dev/null")
    os.system("git add . 2>/dev/null")
    os.system("git commit -m 'Initial' 2>/dev/null || true")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(viewport={"width": 1400, "height": 1000})
        page = await context.new_page()
        
        print("=" * 80)
        print("DETAILED SCREENSHOT TEST - Every Action Captured")
        print("=" * 80)
        
        print("\n[ACTION 1] Navigating to AutoFolio...")
        await page.goto("http://localhost:8000", wait_until="networkidle")
        await asyncio.sleep(2)
        await take_screenshot(page, "01_page_loaded")
        
        print("\n[ACTION 2] Waiting for page to fully render...")
        await asyncio.sleep(2)
        await take_screenshot(page, "02_page_rendered")
        
        print("\n[ACTION 3] Locating welcome message...")
        welcome = page.locator("text=/Hi.*AutoFolio/i").first
        try:
            await expect(welcome).to_be_visible(timeout=10000)
            welcome_text = await welcome.text_content()
            print(f"   Found: {welcome_text[:60]}...")
        except Exception as e:
            print(f"   Warning: {e}")
        await take_screenshot(page, "03_welcome_found")
        
        print("\n[ACTION 4] Finding message input field...")
        message_input = page.locator('textarea').first
        try:
            await expect(message_input).to_be_visible(timeout=5000)
            placeholder = await message_input.get_attribute("placeholder")
            print(f"   Input found, placeholder: {placeholder}")
        except Exception as e:
            print(f"   Error finding input: {e}")
        await take_screenshot(page, "04_input_found")
        
        print("\n[ACTION 5] Clicking on input field...")
        await message_input.click()
        await asyncio.sleep(0.5)
        await take_screenshot(page, "05_input_clicked")
        
        print("\n[ACTION 6] Typing project URL...")
        project_url = "https://github.com/aringadre76/faro-shuffle-demo"
        await message_input.type(project_url, delay=50)
        await asyncio.sleep(0.5)
        await take_screenshot(page, "06_url_typed")
        
        print("\n[ACTION 7] Adding portfolio path to message...")
        await message_input.type(f" portfolio at {test_portfolio}", delay=50)
        await asyncio.sleep(0.5)
        await take_screenshot(page, "07_portfolio_path_added")
        
        print("\n[ACTION 8] Checking current input value...")
        current_value = await message_input.input_value()
        print(f"   Current value: {current_value[:100]}...")
        await take_screenshot(page, "08_input_value_checked")
        
        print("\n[ACTION 9] Looking for send button...")
        send_button = page.locator('button:has-text("Send"), button[type="submit"]').first
        send_count = await send_button.count()
        print(f"   Send button count: {send_count}")
        await take_screenshot(page, "09_send_button_looked")
        
        print("\n[ACTION 10] Clicking send button or pressing Enter...")
        if send_count > 0:
            await send_button.click()
            print("   Clicked Send button")
        else:
            await message_input.press("Enter")
            print("   Pressed Enter")
        await asyncio.sleep(1)
        await take_screenshot(page, "10_message_sent")
        
        print("\n[ACTION 11] Waiting 2 seconds for initial response...")
        await asyncio.sleep(2)
        await take_screenshot(page, "11_after_2_seconds")
        
        print("\n[ACTION 12] Waiting 3 more seconds...")
        await asyncio.sleep(3)
        await take_screenshot(page, "12_after_5_seconds")
        
        print("\n[ACTION 13] Checking page content...")
        page_text = await page.locator("body").text_content()
        print(f"   Page contains: {page_text[:200]}...")
        await take_screenshot(page, "13_page_content_checked")
        
        print("\n[ACTION 14] Looking for all buttons on page...")
        all_buttons = await page.locator("button").all()
        print(f"   Found {len(all_buttons)} buttons")
        for i, btn in enumerate(all_buttons[:10]):
            try:
                text = await btn.text_content()
                aria = await btn.get_attribute("aria-label")
                print(f"   Button {i}: text='{text}', aria='{aria}'")
            except:
                pass
        await take_screenshot(page, "14_all_buttons_found")
        
        print("\n[ACTION 15] Looking for Approve button...")
        approve_btn = page.locator('button:has-text("Approve")').first
        approve_count = await approve_btn.count()
        print(f"   Approve button count: {approve_count}")
        await take_screenshot(page, "15_approve_button_looked")
        
        print("\n[ACTION 16] Looking for Edit button...")
        edit_btn = page.locator('button:has-text("Edit")').first
        edit_count = await edit_btn.count()
        print(f"   Edit button count: {edit_count}")
        await take_screenshot(page, "16_edit_button_looked")
        
        print("\n[ACTION 17] Looking for Cancel button...")
        cancel_btn = page.locator('button:has-text("Cancel")').first
        cancel_count = await cancel_btn.count()
        print(f"   Cancel button count: {cancel_count}")
        await take_screenshot(page, "17_cancel_button_looked")
        
        print("\n[ACTION 18] Waiting 5 more seconds for processing...")
        await asyncio.sleep(5)
        await take_screenshot(page, "18_after_10_seconds")
        
        print("\n[ACTION 19] Checking for processing indicators...")
        page_text = await page.locator("body").text_content()
        if "fetching" in page_text.lower():
            print("   Found 'fetching' in page")
        if "extracting" in page_text.lower():
            print("   Found 'extracting' in page")
        if "cloning" in page_text.lower():
            print("   Found 'cloning' in page")
        if "detecting" in page_text.lower():
            print("   Found 'detecting' in page")
        if "analyzing" in page_text.lower():
            print("   Found 'analyzing' in page")
        await take_screenshot(page, "19_processing_indicators_checked")
        
        print("\n[ACTION 20] Waiting 5 more seconds...")
        await asyncio.sleep(5)
        await take_screenshot(page, "20_after_15_seconds")
        
        print("\n[ACTION 21] Re-checking for config buttons...")
        approve_count = await approve_btn.count()
        edit_count = await edit_btn.count()
        cancel_count = await cancel_btn.count()
        print(f"   Approve: {approve_count}, Edit: {edit_count}, Cancel: {cancel_count}")
        await take_screenshot(page, "21_config_buttons_rechecked")
        
        if approve_count > 0 or edit_count > 0 or cancel_count > 0:
            print("\n[ACTION 22] Config card found! Reading content...")
            body_text = await page.locator("body").text_content()
            for line in body_text.split("\n"):
                line = line.strip()
                if any(kw in line.lower() for kw in ["title:", "description:", "repo url:", "tech stack:", "tags:"]):
                    print(f"   {line}")
            await take_screenshot(page, "22_config_content_read")
            
            if approve_count > 0:
                print("\n[ACTION 23] Clicking Approve button...")
                await approve_btn.click()
                await asyncio.sleep(1)
                await take_screenshot(page, "23_approve_clicked")
                
                print("\n[ACTION 24] Waiting 3 seconds after approve...")
                await asyncio.sleep(3)
                await take_screenshot(page, "24_after_approve_3s")
                
                print("\n[ACTION 25] Waiting 5 more seconds...")
                await asyncio.sleep(5)
                await take_screenshot(page, "25_after_approve_8s")
                
                print("\n[ACTION 26] Checking for patch preview...")
                discard_btn = page.locator('button:has-text("Discard")').first
                apply_btn = page.locator('button:has-text("Apply")').first
                discard_count = await discard_btn.count()
                apply_count = await apply_btn.count()
                print(f"   Discard: {discard_count}, Apply: {apply_count}")
                await take_screenshot(page, "26_patch_buttons_checked")
                
                if discard_count > 0:
                    print("\n[ACTION 27] Clicking Discard button...")
                    await discard_btn.click()
                    await asyncio.sleep(2)
                    await take_screenshot(page, "27_discard_clicked")
        
        print("\n[ACTION 28] Testing starter button...")
        starter = page.get_by_text("Describe a project", exact=False).first
        starter_count = await starter.count()
        print(f"   Starter button count: {starter_count}")
        await take_screenshot(page, "28_starter_button_found")
        
        if starter_count > 0:
            print("\n[ACTION 29] Clicking starter button...")
            await starter.click()
            await asyncio.sleep(1)
            await take_screenshot(page, "29_starter_clicked")
            
            print("\n[ACTION 30] Checking if input was populated...")
            input_val = await message_input.input_value()
            print(f"   Input value: {input_val[:100] if input_val else '(empty)'}")
            await take_screenshot(page, "30_input_after_starter")
        
        print("\n[ACTION 31] Final state screenshot...")
        await take_screenshot(page, "31_final_state")
        
        print("\n" + "=" * 80)
        print("TEST COMPLETE")
        print(f"Total screenshots taken: {screenshot_counter}")
        print("=" * 80)
        
        await asyncio.sleep(2)
        await browser.close()
        
        import shutil
        shutil.rmtree(test_portfolio, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(test_detailed_screenshots())
