import asyncio
import os
from pathlib import Path
from playwright.async_api import async_playwright, expect


async def wait_for_element(page, selector, timeout=30000, description=""):
    try:
        element = page.locator(selector).first
        await expect(element).to_be_visible(timeout=timeout)
        return element
    except Exception as e:
        if description:
            print(f"   Warning: {description} not found: {e}")
        return None


async def test_complete_workflow():
    test_portfolio = Path("/tmp/test-autofolio-portfolio")
    test_portfolio.mkdir(exist_ok=True)
    
    (test_portfolio / "README.md").write_text("# Test Portfolio\n\nA test portfolio for AutoFolio testing.\n")
    (test_portfolio / "package.json").write_text('{"name": "test-portfolio", "version": "1.0.0"}')
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(viewport={"width": 1400, "height": 900})
        page = await context.new_page()
        
        print("=" * 80)
        print("COMPLETE USER WORKFLOW TEST")
        print(f"Test Portfolio: {test_portfolio}")
        print("Project: https://github.com/aringadre76/faro-shuffle-demo")
        print("=" * 80)
        
        print("\n[1/15] Loading AutoFolio web UI...")
        await page.goto("http://localhost:8000", wait_until="networkidle")
        await asyncio.sleep(3)
        print("   Page loaded")
        
        print("\n[2/15] Verifying welcome message...")
        welcome = await wait_for_element(page, "text=/Hi.*AutoFolio/i", description="Welcome message")
        if welcome:
            welcome_text = await welcome.text_content()
            print(f"   Found: {welcome_text[:70]}...")
        
        print("\n[3/15] Finding message input...")
        message_input = await wait_for_element(page, "textarea", description="Message input")
        if not message_input:
            print("   ERROR: Cannot find message input!")
            await browser.close()
            return
        print("   Input field ready")
        
        print("\n[4/15] Entering project URL with portfolio path...")
        project_url = "https://github.com/aringadre76/faro-shuffle-demo"
        user_message = f"Add {project_url} to my portfolio at {test_portfolio}"
        
        await message_input.fill(user_message)
        print(f"   Message entered: {user_message[:80]}...")
        await asyncio.sleep(1)
        
        print("\n[5/15] Sending message...")
        send_button = page.locator('button:has-text("Send"), button[type="submit"]').first
        if await send_button.count() > 0:
            await send_button.click()
            print("   Clicked Send button")
        else:
            await message_input.press("Enter")
            print("   Pressed Enter")
        
        print("\n[6/15] Waiting for initial response (up to 30 seconds)...")
        await asyncio.sleep(5)
        
        for i in range(10):
            page_text = await page.locator("body").text_content()
            
            if "fetching" in page_text.lower() or "extracting" in page_text.lower() or "cloning" in page_text.lower():
                print(f"   Processing... (attempt {i+1}/10)")
                await asyncio.sleep(3)
                continue
            
            if "extracted project" in page_text.lower() or "title:" in page_text.lower():
                print("   Config extraction completed!")
                break
            
            if "portfolio" in page_text.lower() and ("path" in page_text.lower() or "where" in page_text.lower()):
                if "not a directory" not in page_text.lower():
                    print("   System is validating portfolio path...")
                    await asyncio.sleep(2)
                    break
            
            await asyncio.sleep(2)
        
        await page.screenshot(path="workflow_after_send.png", full_page=True)
        print("   Screenshot: workflow_after_send.png")
        
        print("\n[7/15] Checking for config card with action buttons...")
        await asyncio.sleep(2)
        
        approve_btn = page.locator('button:has-text("Approve")').first
        edit_btn = page.locator('button:has-text("Edit")').first
        cancel_btn = page.locator('button:has-text("Cancel")').first
        
        config_displayed = False
        if await approve_btn.count() > 0:
            print("   Found Approve button!")
            config_displayed = True
        if await edit_btn.count() > 0:
            print("   Found Edit button!")
            config_displayed = True
        if await cancel_btn.count() > 0:
            print("   Found Cancel button!")
            config_displayed = True
        
        if config_displayed:
            print("\n[8/15] Reading extracted project configuration...")
            body_text = await page.locator("body").text_content()
            
            config_info = []
            for line in body_text.split("\n"):
                line = line.strip()
                if any(keyword in line.lower() for keyword in ["title:", "description:", "repo url:", "demo url:", "tech stack:", "tags:"]):
                    config_info.append(line)
                    print(f"   {line}")
            
            await page.screenshot(path="workflow_config_displayed.png", full_page=True)
            print("   Screenshot: workflow_config_displayed.png")
            
            print("\n[9/15] Testing Edit button...")
            if await edit_btn.count() > 0:
                await edit_btn.click()
                await asyncio.sleep(2)
                print("   Edit button clicked")
                
                edit_options = page.locator('button:has-text("Title"), button:has-text("Description"), button:has-text("Done")').first
                if await edit_options.count() > 0:
                    print("   Edit options displayed")
                    done_btn = page.locator('button:has-text("Done")').first
                    if await done_btn.count() > 0:
                        await done_btn.click()
                        await asyncio.sleep(1)
                        print("   Clicked Done (cancelled edit)")
                
                await page.screenshot(path="workflow_edit_mode.png", full_page=True)
                print("   Screenshot: workflow_edit_mode.png")
            
            print("\n[10/15] Testing Cancel button...")
            cancel_btn = page.locator('button:has-text("Cancel")').first
            if await cancel_btn.count() > 0:
                await cancel_btn.click()
                await asyncio.sleep(2)
                print("   Cancel clicked - config discarded")
                await page.screenshot(path="workflow_cancelled.png", full_page=True)
                print("   Screenshot: workflow_cancelled.png")
            
            print("\n[11/15] Re-entering project to test Approve flow...")
            await message_input.fill(user_message)
            await asyncio.sleep(1)
            
            if await send_button.count() > 0:
                await send_button.click()
            else:
                await message_input.press("Enter")
            
            print("   Waiting for config again...")
            await asyncio.sleep(8)
            
            approve_btn = page.locator('button:has-text("Approve")').first
            if await approve_btn.count() > 0:
                print("\n[12/15] Testing Approve button...")
                await approve_btn.click()
                await asyncio.sleep(2)
                print("   Approve clicked")
                
                print("\n[13/15] Waiting for patch generation (up to 60 seconds)...")
                for i in range(20):
                    page_text = await page.locator("body").text_content()
                    
                    if "detecting" in page_text.lower() or "analyzing" in page_text.lower() or "generating" in page_text.lower():
                        print(f"   Processing... (attempt {i+1}/20)")
                        await asyncio.sleep(3)
                        continue
                    
                    if "patch preview" in page_text.lower() or "diff" in page_text.lower() or "apply" in page_text.lower():
                        print("   Patch preview generated!")
                        break
                    
                    if "error" in page_text.lower() and "no valid patches" not in page_text.lower():
                        print(f"   Error detected: {page_text[:200]}")
                        break
                    
                    await asyncio.sleep(3)
                
                await page.screenshot(path="workflow_patch_preview.png", full_page=True)
                print("   Screenshot: workflow_patch_preview.png")
                
                apply_btn = page.locator('button:has-text("Apply")').first
                discard_btn = page.locator('button:has-text("Discard")').first
                
                if await discard_btn.count() > 0:
                    print("\n[14/15] Testing Discard button...")
                    await discard_btn.click()
                    await asyncio.sleep(2)
                    print("   Discard clicked - patches discarded")
                    await page.screenshot(path="workflow_discarded.png", full_page=True)
                    print("   Screenshot: workflow_discarded.png")
                elif await apply_btn.count() > 0:
                    print("   Apply button found (but skipping actual application)")
                else:
                    print("   No patch action buttons found")
        else:
            print("   Config card not displayed")
            page_text = await page.locator("body").text_content()
            print(f"   Current page content: {page_text[:300]}...")
        
        print("\n[15/15] Testing UI elements and interactions...")
        
        print("   Testing starter buttons...")
        starters = ["Describe a project", "Add a project from GitHub"]
        for starter_text in starters:
            starter = page.get_by_text(starter_text, exact=False).first
            if await starter.count() > 0:
                print(f"   Found starter: {starter_text}")
        
        print("   Testing input field functionality...")
        await message_input.clear()
        await message_input.fill("Test input")
        value = await message_input.input_value()
        assert value == "Test input"
        print("   Input field works correctly")
        
        await page.screenshot(path="workflow_final_state.png", full_page=True)
        print("   Screenshot: workflow_final_state.png")
        
        print("\n" + "=" * 80)
        print("COMPLETE WORKFLOW TEST FINISHED")
        print("=" * 80)
        print("\nScreenshots generated:")
        print("  - workflow_after_send.png")
        print("  - workflow_config_displayed.png")
        print("  - workflow_edit_mode.png")
        print("  - workflow_cancelled.png")
        print("  - workflow_patch_preview.png")
        print("  - workflow_discarded.png")
        print("  - workflow_final_state.png")
        
        await asyncio.sleep(2)
        await browser.close()
        
        print(f"\nCleaning up test portfolio: {test_portfolio}")
        import shutil
        shutil.rmtree(test_portfolio, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(test_complete_workflow())
