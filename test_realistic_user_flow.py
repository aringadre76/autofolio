import asyncio
import os
from pathlib import Path
from playwright.async_api import async_playwright, expect


async def test_realistic_user_flow():
    test_portfolio = Path("/tmp/test-autofolio-portfolio")
    test_portfolio.mkdir(exist_ok=True)
    
    (test_portfolio / "README.md").write_text("# Test Portfolio\n\nA test portfolio.\n")
    (test_portfolio / "package.json").write_text('{"name": "test-portfolio", "version": "1.0.0"}')
    
    os.chdir(str(test_portfolio))
    os.system("git init 2>/dev/null")
    os.system("git config user.email 'test@test.com' 2>/dev/null")
    os.system("git config user.name 'Test User' 2>/dev/null")
    os.system("git add . 2>/dev/null")
    os.system("git commit -m 'Initial commit' 2>/dev/null || true")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(viewport={"width": 1400, "height": 1000})
        page = await context.new_page()
        
        print("=" * 80)
        print("REALISTIC USER WORKFLOW TEST")
        print(f"Portfolio: {test_portfolio}")
        print("Project: https://github.com/aringadre76/faro-shuffle-demo")
        print("=" * 80)
        
        print("\n[1] Opening AutoFolio...")
        await page.goto("http://localhost:8000", wait_until="networkidle")
        await asyncio.sleep(3)
        
        print("\n[2] Verifying page loaded...")
        title = await page.title()
        print(f"   Title: {title}")
        
        welcome = page.locator("text=/Hi.*AutoFolio/i").first
        await expect(welcome).to_be_visible(timeout=10000)
        print("   Welcome message visible")
        
        print("\n[3] Finding and clicking settings...")
        settings_selectors = [
            'button[aria-label*="settings" i]',
            'button[title*="settings" i]',
            'button:has-text("Settings")',
            '[role="button"][aria-label*="settings" i]',
            'svg[aria-label*="settings" i]',
            'button:has(svg)',
        ]
        
        settings_opened = False
        for selector in settings_selectors:
            try:
                btn = page.locator(selector).first
                if await btn.count() > 0:
                    await btn.click()
                    await asyncio.sleep(2)
                    print(f"   Clicked settings using: {selector}")
                    settings_opened = True
                    break
            except:
                continue
        
        if not settings_opened:
            print("   Settings button not found - checking page structure...")
            all_buttons = await page.locator("button").all()
            print(f"   Found {len(all_buttons)} buttons on page")
            for i, btn in enumerate(all_buttons[:5]):
                try:
                    text = await btn.text_content()
                    aria_label = await btn.get_attribute("aria-label")
                    print(f"   Button {i}: text='{text}', aria-label='{aria_label}'")
                except:
                    pass
        
        await page.screenshot(path="test_initial.png", full_page=True)
        print("   Screenshot: test_initial.png")
        
        print("\n[4] Looking for portfolio path input in settings...")
        await asyncio.sleep(2)
        
        portfolio_input = page.locator('input[placeholder*="portfolio" i], input[id*="portfolio" i], input[name*="portfolio" i]').first
        if await portfolio_input.count() > 0:
            print("   Found portfolio input field")
            await portfolio_input.fill(str(test_portfolio))
            print(f"   Entered portfolio path: {test_portfolio}")
            await asyncio.sleep(1)
            
            save_btn = page.locator('button:has-text("Save"), button:has-text("Apply"), button[type="submit"]').first
            if await save_btn.count() > 0:
                await save_btn.click()
                await asyncio.sleep(1)
                print("   Saved settings")
        else:
            print("   Portfolio input not found in settings (may use different UI)")
        
        await page.screenshot(path="test_settings.png", full_page=True)
        print("   Screenshot: test_settings.png")
        
        print("\n[5] Finding message input...")
        message_input = page.locator('textarea').first
        await expect(message_input).to_be_visible(timeout=5000)
        print("   Message input ready")
        
        print("\n[6] Entering project URL...")
        project_url = "https://github.com/aringadre76/faro-shuffle-demo"
        await message_input.fill(project_url)
        print(f"   Entered: {project_url}")
        await asyncio.sleep(1)
        
        print("\n[7] Sending message...")
        send_button = page.locator('button:has-text("Send"), button[type="submit"]').first
        if await send_button.count() > 0:
            await send_button.click()
            print("   Clicked Send")
        else:
            await message_input.press("Enter")
            print("   Pressed Enter")
        
        print("\n[8] Waiting for processing (up to 90 seconds)...")
        await asyncio.sleep(5)
        
        for attempt in range(30):
            page_text = await page.locator("body").text_content()
            
            if "fetching" in page_text.lower() or "extracting" in page_text.lower() or "cloning" in page_text.lower():
                print(f"   Processing... ({attempt+1}/30)")
                await asyncio.sleep(3)
                continue
            
            if "extracted project" in page_text.lower() or "title:" in page_text.lower():
                print("   Config extracted!")
                break
            
            if "error" in page_text.lower() and "portfolio" in page_text.lower():
                print(f"   Portfolio error: {page_text[:200]}")
                break
            
            await asyncio.sleep(3)
        
        await page.screenshot(path="test_processing.png", full_page=True)
        print("   Screenshot: test_processing.png")
        
        print("\n[9] Checking for config card...")
        await asyncio.sleep(3)
        
        approve_btn = page.locator('button:has-text("Approve")').first
        edit_btn = page.locator('button:has-text("Edit")').first
        cancel_btn = page.locator('button:has-text("Cancel")').first
        
        if await approve_btn.count() > 0 or await edit_btn.count() > 0 or await cancel_btn.count() > 0:
            print("   Config card displayed!")
            
            body_text = await page.locator("body").text_content()
            print("\n   Extracted configuration:")
            for line in body_text.split("\n"):
                line = line.strip()
                if any(kw in line.lower() for kw in ["title:", "description:", "repo url:", "tech stack:", "tags:"]):
                    print(f"     {line}")
            
            await page.screenshot(path="test_config.png", full_page=True)
            print("   Screenshot: test_config.png")
            
            print("\n[10] Testing Approve button...")
            if await approve_btn.count() > 0:
                await approve_btn.click()
                print("   Approve clicked")
                await asyncio.sleep(2)
                
                print("\n[11] Waiting for patch generation (up to 120 seconds)...")
                for attempt in range(40):
                    page_text = await page.locator("body").text_content()
                    
                    if "detecting" in page_text.lower() or "analyzing" in page_text.lower():
                        print(f"   Analyzing... ({attempt+1}/40)")
                        await asyncio.sleep(3)
                        continue
                    
                    if "patch preview" in page_text.lower() or "diff" in page_text.lower():
                        print("   Patch preview generated!")
                        break
                    
                    if "no valid patches" in page_text.lower():
                        print("   No patches generated (may need valid portfolio structure)")
                        break
                    
                    await asyncio.sleep(3)
                
                await page.screenshot(path="test_patches.png", full_page=True)
                print("   Screenshot: test_patches.png")
                
                discard_btn = page.locator('button:has-text("Discard")').first
                if await discard_btn.count() > 0:
                    print("\n[12] Testing Discard button...")
                    await discard_btn.click()
                    await asyncio.sleep(2)
                    print("   Discarded patches")
                    await page.screenshot(path="test_discarded.png", full_page=True)
                    print("   Screenshot: test_discarded.png")
        else:
            print("   Config card not displayed")
            page_text = await page.locator("body").text_content()
            print(f"   Current state: {page_text[:400]}...")
        
        print("\n[13] Testing starter buttons...")
        starter = page.get_by_text("Describe a project", exact=False).first
        if await starter.count() > 0:
            await starter.click()
            await asyncio.sleep(2)
            input_val = await message_input.input_value()
            if input_val:
                print(f"   Starter populated: {input_val[:60]}...")
        
        print("\n[14] Final screenshot...")
        await page.screenshot(path="test_final.png", full_page=True)
        print("   Screenshot: test_final.png")
        
        print("\n" + "=" * 80)
        print("TEST COMPLETE")
        print("=" * 80)
        
        await asyncio.sleep(2)
        await browser.close()
        
        import shutil
        shutil.rmtree(test_portfolio, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(test_realistic_user_flow())
