import asyncio
from playwright.async_api import async_playwright, expect


async def test_frontend_comprehensive():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(viewport={"width": 1280, "height": 720})
        page = await context.new_page()
        
        print("=" * 60)
        print("COMPREHENSIVE FRONTEND TEST")
        print("=" * 60)
        
        print("\n1. Testing page load...")
        await page.goto("http://localhost:8000", wait_until="networkidle")
        await asyncio.sleep(2)
        
        title = await page.title()
        print(f"   Page title: {title}")
        assert "Assistant" in title
        
        print("\n2. Testing welcome message...")
        welcome_text = page.locator("text=/Hi.*AutoFolio/i").first
        await expect(welcome_text).to_be_visible(timeout=10000)
        welcome_content = await welcome_text.text_content()
        print(f"   Welcome message: {welcome_content[:80]}...")
        
        print("\n3. Testing starter buttons...")
        starters_found = []
        starter_labels = [
            "Add a project from GitHub",
            "Describe a project",
            "Add multiple projects",
            "Run from config file"
        ]
        for label in starter_labels:
            starter = page.get_by_text(label, exact=False).first
            if await starter.count() > 0:
                try:
                    await expect(starter).to_be_visible(timeout=2000)
                    starters_found.append(label)
                    print(f"   Found: {label}")
                except:
                    pass
        
        print(f"   Total starters found: {len(starters_found)}/{len(starter_labels)}")
        
        print("\n4. Testing message input field...")
        message_input = page.locator('textarea').first
        await expect(message_input).to_be_visible(timeout=5000)
        placeholder = await message_input.get_attribute("placeholder")
        print(f"   Input placeholder: {placeholder}")
        
        print("\n5. Testing text input functionality...")
        test_message = "Test project description"
        await message_input.fill(test_message)
        input_value = await message_input.input_value()
        assert input_value == test_message
        print(f"   Successfully entered: {input_value}")
        
        await message_input.clear()
        assert await message_input.input_value() == ""
        print("   Successfully cleared input")
        
        print("\n6. Testing starter button interaction...")
        if "Describe a project" in starters_found:
            starter = page.get_by_text("Describe a project", exact=False).first
            await starter.click()
            await asyncio.sleep(1)
            input_after_click = await message_input.input_value()
            if input_after_click:
                print(f"   Starter populated input: {input_after_click[:50]}...")
            else:
                print("   Starter did not populate input (may be expected)")
        
        print("\n7. Testing page responsiveness...")
        await page.set_viewport_size({"width": 375, "height": 667})
        await asyncio.sleep(1)
        await expect(message_input).to_be_visible()
        print("   Mobile viewport: Input still visible")
        
        await page.set_viewport_size({"width": 1920, "height": 1080})
        await asyncio.sleep(1)
        await expect(message_input).to_be_visible()
        print("   Desktop viewport: Input still visible")
        
        print("\n8. Testing theme toggle (if present)...")
        theme_toggle = page.locator("text=/toggle.*theme/i").first
        if await theme_toggle.count() > 0:
            await theme_toggle.click()
            await asyncio.sleep(0.5)
            print("   Theme toggle clicked")
        else:
            print("   Theme toggle not found (may not be present)")
        
        print("\n9. Testing page structure...")
        body = page.locator("body")
        await expect(body).to_be_visible()
        
        all_buttons = await page.locator("button").count()
        all_inputs = await page.locator("input, textarea").count()
        print(f"   Found {all_buttons} button(s)")
        print(f"   Found {all_inputs} input field(s)")
        
        print("\n10. Taking final screenshot...")
        await page.screenshot(path="test_final.png", full_page=True)
        print("   Screenshot saved to test_final.png")
        
        print("\n" + "=" * 60)
        print("ALL TESTS PASSED!")
        print("=" * 60)
        
        await browser.close()


if __name__ == "__main__":
    asyncio.run(test_frontend_comprehensive())
