import asyncio
from playwright.async_api import async_playwright, expect, TimeoutError as PlaywrightTimeout


async def test_full_user_workflow():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(viewport={"width": 1280, "height": 720})
        page = await context.new_page()
        
        print("=" * 70)
        print("FULL USER WORKFLOW TEST - Testing with faro-shuffle-demo")
        print("=" * 70)
        
        print("\n[Step 1] Navigating to AutoFolio web UI...")
        await page.goto("http://localhost:8000", wait_until="networkidle")
        await asyncio.sleep(2)
        print("   Page loaded successfully")
        
        print("\n[Step 2] Verifying welcome message...")
        welcome = page.locator("text=/Hi.*AutoFolio/i").first
        await expect(welcome).to_be_visible(timeout=10000)
        welcome_text = await welcome.text_content()
        print(f"   Welcome message: {welcome_text[:60]}...")
        
        print("\n[Step 3] Locating message input field...")
        message_input = page.locator('textarea').first
        await expect(message_input).to_be_visible(timeout=5000)
        print("   Input field found")
        
        print("\n[Step 4] Entering project URL and portfolio path...")
        project_url = "https://github.com/aringadre76/faro-shuffle-demo"
        portfolio_path = "/tmp/test-portfolio"
        
        test_message = f"Add {project_url} to my portfolio at {portfolio_path}"
        await message_input.fill(test_message)
        print(f"   Entered: {test_message}")
        
        await asyncio.sleep(1)
        
        print("\n[Step 5] Looking for send button or submitting with Enter...")
        send_button = page.locator('button:has-text("Send"), button[type="submit"], button[aria-label*="send" i]').first
        if await send_button.count() > 0:
            await send_button.click()
            print("   Clicked send button")
        else:
            await message_input.press("Enter")
            print("   Pressed Enter to send")
        
        print("\n[Step 6] Waiting for response...")
        await asyncio.sleep(3)
        
        print("\n[Step 7] Checking for error messages or portfolio path prompt...")
        page_text = await page.locator("body").text_content()
        
        if "portfolio" in page_text.lower() and ("path" in page_text.lower() or "where" in page_text.lower()):
            print("   System is asking for portfolio path (expected if path doesn't exist)")
            print("   This is normal behavior - the system validates the portfolio path")
        else:
            print("   No portfolio path error detected")
        
        print("\n[Step 8] Taking screenshot of current state...")
        await page.screenshot(path="workflow_step1.png", full_page=True)
        print("   Screenshot saved: workflow_step1.png")
        
        print("\n[Step 9] Testing with a valid portfolio path message...")
        await message_input.clear()
        await asyncio.sleep(0.5)
        
        valid_message = f"{project_url} portfolio at /tmp"
        await message_input.fill(valid_message)
        print(f"   Entered: {valid_message}")
        
        if await send_button.count() > 0:
            await send_button.click()
        else:
            await message_input.press("Enter")
        
        print("\n[Step 10] Waiting for processing...")
        await asyncio.sleep(5)
        
        print("\n[Step 11] Checking for config card or action buttons...")
        await page.screenshot(path="workflow_step2.png", full_page=True)
        print("   Screenshot saved: workflow_step2.png")
        
        approve_button = page.locator('button:has-text("Approve"), [data-action="approve_config"]').first
        edit_button = page.locator('button:has-text("Edit"), [data-action="edit_config"]').first
        cancel_button = page.locator('button:has-text("Cancel"), [data-action="cancel_config"]').first
        
        config_found = False
        if await approve_button.count() > 0:
            print("   Found Approve button - config card is displayed")
            config_found = True
        elif await edit_button.count() > 0:
            print("   Found Edit button - config card is displayed")
            config_found = True
        elif await cancel_button.count() > 0:
            print("   Found Cancel button - config card is displayed")
            config_found = True
        
        if config_found:
            print("\n[Step 12] Reading extracted project config...")
            body_text = await page.locator("body").text_content()
            
            if "Title:" in body_text or "title" in body_text.lower():
                print("   Config information is displayed")
                lines = body_text.split("\n")
                for line in lines[:20]:
                    if any(keyword in line.lower() for keyword in ["title", "description", "repo", "tech", "tag"]):
                        print(f"   {line.strip()}")
            
            print("\n[Step 13] Testing Cancel button...")
            if await cancel_button.count() > 0:
                await cancel_button.click()
                await asyncio.sleep(2)
                print("   Cancel button clicked")
                await page.screenshot(path="workflow_cancelled.png", full_page=True)
                print("   Screenshot saved: workflow_cancelled.png")
        else:
            print("   Config card not found yet (may still be processing)")
            print("   Checking page content...")
            body_text = await page.locator("body").text_content()
            print(f"   Page contains: {body_text[:300]}...")
        
        print("\n[Step 14] Testing starter button interaction...")
        await message_input.clear()
        starter = page.get_by_text("Describe a project", exact=False).first
        if await starter.count() > 0:
            await starter.click()
            await asyncio.sleep(2)
            input_value = await message_input.input_value()
            if input_value:
                print(f"   Starter populated: {input_value[:50]}...")
            else:
                print("   Starter clicked but didn't populate input")
        
        print("\n[Step 15] Testing settings access...")
        settings_selectors = [
            'button[aria-label*="settings" i]',
            'button[title*="settings" i]',
            'button:has-text("Settings")',
            '[data-testid*="settings"]',
            'svg[aria-label*="settings" i]'
        ]
        
        settings_found = False
        for selector in settings_selectors:
            settings_btn = page.locator(selector).first
            if await settings_btn.count() > 0:
                try:
                    await settings_btn.click()
                    await asyncio.sleep(1)
                    print("   Settings opened")
                    settings_found = True
                    await page.screenshot(path="workflow_settings.png", full_page=True)
                    print("   Screenshot saved: workflow_settings.png")
                    break
                except:
                    continue
        
        if not settings_found:
            print("   Settings button not found or not clickable")
        
        print("\n[Step 16] Final page state...")
        await page.screenshot(path="workflow_final.png", full_page=True)
        print("   Screenshot saved: workflow_final.png")
        
        print("\n" + "=" * 70)
        print("USER WORKFLOW TEST COMPLETED")
        print("=" * 70)
        print("\nCheck the screenshots for visual verification:")
        print("  - workflow_step1.png: Initial state")
        print("  - workflow_step2.png: After sending project URL")
        print("  - workflow_cancelled.png: After cancelling config")
        print("  - workflow_settings.png: Settings panel (if found)")
        print("  - workflow_final.png: Final state")
        
        await asyncio.sleep(2)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(test_full_user_workflow())
