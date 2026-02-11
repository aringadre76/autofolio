import asyncio
import os
from pathlib import Path
from playwright.async_api import async_playwright, expect


async def test_full_user_journey():
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
        print("FULL USER JOURNEY TEST")
        print("=" * 80)
        
        print("\n[STEP 1] Loading AutoFolio...")
        await page.goto("http://localhost:8000", wait_until="networkidle")
        await asyncio.sleep(3)
        
        print("\n[STEP 2] Verifying initial state...")
        welcome = page.locator("text=/Hi.*AutoFolio/i").first
        await expect(welcome).to_be_visible(timeout=10000)
        print("   Welcome message visible")
        
        message_input = page.locator('textarea').first
        await expect(message_input).to_be_visible(timeout=5000)
        print("   Message input ready")
        
        await page.screenshot(path="journey_01_initial.png", full_page=True)
        
        print("\n[STEP 3] Opening settings panel...")
        settings_buttons = page.locator("button").all()
        settings_clicked = False
        
        for btn in await settings_buttons:
            try:
                aria_label = await btn.get_attribute("aria-label")
                title_attr = await btn.get_attribute("title")
                text_content = await btn.text_content()
                
                if aria_label and "settings" in aria_label.lower():
                    await btn.click()
                    await asyncio.sleep(2)
                    print(f"   Clicked settings via aria-label: {aria_label}")
                    settings_clicked = True
                    break
                elif title_attr and "settings" in title_attr.lower():
                    await btn.click()
                    await asyncio.sleep(2)
                    print(f"   Clicked settings via title: {title_attr}")
                    settings_clicked = True
                    break
            except:
                continue
        
        if not settings_clicked:
            svg_buttons = await page.locator("button:has(svg)").all()
            for btn in svg_buttons[:3]:
                try:
                    await btn.click()
                    await asyncio.sleep(2)
                    page_text = await page.locator("body").text_content()
                    if "portfolio" in page_text.lower() and "path" in page_text.lower():
                        print("   Settings opened (via SVG button)")
                        settings_clicked = True
                        break
                except:
                    continue
        
        await page.screenshot(path="journey_02_settings.png", full_page=True)
        
        if settings_clicked:
            print("\n[STEP 4] Filling portfolio path in settings...")
            await asyncio.sleep(1)
            
            inputs = await page.locator("input").all()
            for inp in inputs:
                try:
                    placeholder = await inp.get_attribute("placeholder")
                    input_id = await inp.get_attribute("id")
                    name = await inp.get_attribute("name")
                    
                    if placeholder and "portfolio" in placeholder.lower():
                        await inp.fill(str(test_portfolio))
                        print(f"   Filled portfolio path via placeholder: {placeholder}")
                        await asyncio.sleep(1)
                        break
                    elif input_id and "portfolio" in input_id.lower():
                        await inp.fill(str(test_portfolio))
                        print(f"   Filled portfolio path via id: {input_id}")
                        await asyncio.sleep(1)
                        break
                    elif name and "portfolio" in name.lower():
                        await inp.fill(str(test_portfolio))
                        print(f"   Filled portfolio path via name: {name}")
                        await asyncio.sleep(1)
                        break
                except:
                    continue
            
            await page.screenshot(path="journey_03_settings_filled.png", full_page=True)
            
            close_btn = page.locator('button:has-text("Close"), button:has-text("Done"), button[aria-label*="close" i]').first
            if await close_btn.count() > 0:
                await close_btn.click()
                await asyncio.sleep(1)
                print("   Closed settings")
        
        print("\n[STEP 5] Entering project URL in message...")
        project_url = "https://github.com/aringadre76/faro-shuffle-demo"
        await message_input.fill(project_url)
        print(f"   Entered: {project_url}")
        await asyncio.sleep(1)
        
        await page.screenshot(path="journey_04_message_entered.png", full_page=True)
        
        print("\n[STEP 6] Sending message...")
        send_button = page.locator('button:has-text("Send"), button[type="submit"]').first
        if await send_button.count() > 0:
            await send_button.click()
        else:
            await message_input.press("Enter")
        print("   Message sent")
        
        print("\n[STEP 7] Waiting for GitHub metadata fetch...")
        await asyncio.sleep(5)
        
        for i in range(20):
            page_text = await page.locator("body").text_content()
            
            if "fetching" in page_text.lower() or "cloning" in page_text.lower():
                print(f"   Fetching/cloning... ({i+1}/20)")
                await asyncio.sleep(3)
                continue
            
            if "extracting" in page_text.lower() or "metadata" in page_text.lower():
                print(f"   Extracting metadata... ({i+1}/20)")
                await asyncio.sleep(3)
                continue
            
            if "extracted project" in page_text.lower() or "title:" in page_text.lower():
                print("   Config extracted!")
                break
            
            if "portfolio" in page_text.lower() and ("path" in page_text.lower() or "where" in page_text.lower()):
                if i > 5:
                    print("   Still asking for portfolio path - trying to include in message")
                    await message_input.clear()
                    await message_input.fill(f"{project_url} portfolio at {test_portfolio}")
                    await asyncio.sleep(1)
                    if await send_button.count() > 0:
                        await send_button.click()
                    else:
                        await message_input.press("Enter")
                    await asyncio.sleep(5)
                else:
                    print("   Portfolio path requested")
                    await asyncio.sleep(3)
                continue
            
            await asyncio.sleep(2)
        
        await page.screenshot(path="journey_05_processing.png", full_page=True)
        
        print("\n[STEP 8] Checking for config card...")
        await asyncio.sleep(3)
        
        approve_btn = page.locator('button:has-text("Approve")').first
        edit_btn = page.locator('button:has-text("Edit")').first
        cancel_btn = page.locator('button:has-text("Cancel")').first
        
        config_found = False
        if await approve_btn.count() > 0:
            config_found = True
            print("   Approve button found!")
        if await edit_btn.count() > 0:
            config_found = True
            print("   Edit button found!")
        if await cancel_btn.count() > 0:
            config_found = True
            print("   Cancel button found!")
        
        if config_found:
            print("\n[STEP 9] Reading extracted configuration...")
            body_text = await page.locator("body").text_content()
            
            config_lines = []
            for line in body_text.split("\n"):
                line = line.strip()
                if any(kw in line.lower() for kw in ["title:", "description:", "repo url:", "demo url:", "tech stack:", "tags:"]):
                    config_lines.append(line)
                    print(f"   {line}")
            
            await page.screenshot(path="journey_06_config.png", full_page=True)
            
            print("\n[STEP 10] Testing Edit button...")
            if await edit_btn.count() > 0:
                await edit_btn.click()
                await asyncio.sleep(2)
                print("   Edit clicked")
                
                done_btn = page.locator('button:has-text("Done")').first
                if await done_btn.count() > 0:
                    await done_btn.click()
                    await asyncio.sleep(1)
                    print("   Done clicked (cancelled edit)")
            
            print("\n[STEP 11] Testing Approve button...")
            approve_btn = page.locator('button:has-text("Approve")').first
            if await approve_btn.count() > 0:
                await approve_btn.click()
                print("   Approve clicked")
                await asyncio.sleep(2)
                
                print("\n[STEP 12] Waiting for patch generation...")
                for i in range(30):
                    page_text = await page.locator("body").text_content()
                    
                    if "detecting" in page_text.lower():
                        print(f"   Detecting stack... ({i+1}/30)")
                        await asyncio.sleep(3)
                        continue
                    
                    if "analyzing" in page_text.lower() or "generating" in page_text.lower():
                        print(f"   Analyzing/generating... ({i+1}/30)")
                        await asyncio.sleep(3)
                        continue
                    
                    if "patch preview" in page_text.lower() or "diff" in page_text.lower():
                        print("   Patch preview generated!")
                        break
                    
                    if "no valid patches" in page_text.lower() or "no patches" in page_text.lower():
                        print("   No patches generated")
                        break
                    
                    await asyncio.sleep(3)
                
                await page.screenshot(path="journey_07_patches.png", full_page=True)
                
                discard_btn = page.locator('button:has-text("Discard")').first
                if await discard_btn.count() > 0:
                    print("\n[STEP 13] Testing Discard button...")
                    await discard_btn.click()
                    await asyncio.sleep(2)
                    print("   Discarded patches")
                    await page.screenshot(path="journey_08_discarded.png", full_page=True)
        else:
            print("   Config card not found")
            page_text = await page.locator("body").text_content()
            print(f"   Current page: {page_text[:500]}...")
        
        print("\n[STEP 14] Testing starter buttons...")
        starter = page.get_by_text("Describe a project", exact=False).first
        if await starter.count() > 0:
            await starter.click()
            await asyncio.sleep(2)
            val = await message_input.input_value()
            if val:
                print(f"   Starter populated: {val[:50]}...")
        
        print("\n[STEP 15] Final screenshot...")
        await page.screenshot(path="journey_09_final.png", full_page=True)
        
        print("\n" + "=" * 80)
        print("USER JOURNEY TEST COMPLETE")
        print("=" * 80)
        print("\nScreenshots:")
        print("  journey_01_initial.png - Initial page")
        print("  journey_02_settings.png - Settings opened")
        print("  journey_03_settings_filled.png - Settings filled")
        print("  journey_04_message_entered.png - Message entered")
        print("  journey_05_processing.png - Processing")
        print("  journey_06_config.png - Config displayed")
        print("  journey_07_patches.png - Patches generated")
        print("  journey_08_discarded.png - Patches discarded")
        print("  journey_09_final.png - Final state")
        
        await asyncio.sleep(2)
        await browser.close()
        
        import shutil
        shutil.rmtree(test_portfolio, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(test_full_user_journey())
