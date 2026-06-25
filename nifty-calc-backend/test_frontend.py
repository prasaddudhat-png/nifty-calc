import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        page.on("console", lambda msg: print(f"LOG: {msg.text}"))
        page.on("pageerror", lambda err: print(f"ERROR: {err}"))
        # 1. Navigate to Settings page
        await page.goto("http://localhost:8080/settings.html")
        await page.wait_for_timeout(2000)
        
        # 2. Enter backend URL without protocol
        await page.fill("#backendApiUrl", "127.0.0.1:8000")
        await page.click("#connSaveBtn")
        await page.wait_for_timeout(2000)
        
        # 3. Check if it normalized to http://127.0.0.1:8000
        saved_val = await page.input_value("#backendApiUrl")
        print(f"Normalized saved URL: {saved_val}")
        
        # 4. Navigate to index.html to verify updates
        await page.goto("http://localhost:8080/index.html")
        await page.wait_for_timeout(6000)
        
        # 5. Extract values
        synth = await page.inner_text("#synthResult0")
        ce = await page.inner_text("#ceResult0")
        pe = await page.inner_text("#peResult0")
        spot = await page.inner_text("#spotResult0")
        diff = await page.inner_text("#diffResult0")
        update_time = await page.inner_text("#lastUpdateTime")
        box_status = await page.inner_text("#statusText")
        
        print("--- Verified Display Values ---")
        print(f"Status: {box_status}")
        print(f"Synthetic Future: {synth}")
        print(f"CE Price: {ce.replace('₹', 'Rs. ')}")
        print(f"PE Price: {pe.replace('₹', 'Rs. ')}")
        print(f"Spot Price: {spot.replace('₹', 'Rs. ')}")
        print(f"Premium/Discount: {diff}")
        print(f"Last Update Time: {update_time}")
        print("---------------------------------")
        
        await browser.close()

asyncio.run(run())
