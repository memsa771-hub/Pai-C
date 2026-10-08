"""Browser/API smoke check against docker-compose.offline.yml; no model APIs.

Run in the existing browser backend image on pai-consolidation-check_host_access.
Browser request forwarding keeps the public localhost origins intact while the
container reaches the two test services by their Compose names.
"""

import asyncio
import json

from playwright.async_api import async_playwright


async def main():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context()
        api = context.request
        origin = {"Origin": "http://localhost:13000"}
        login = await api.post("http://backend:8000/v1/auth/session", headers={
            **origin, "Authorization": "Bearer offline-provider-token"})
        assert login.status == 200, await login.text()
        workspace = (await login.json())["data"]["workspace"]["workspaceId"]
        onboarding = await api.post(
            f"http://backend:8000/v1/student-profile/onboarding?network={workspace}",
            headers=origin, data={"answers": {
                "fullName": "Offline Student", "preferredName": "Student",
                "statusCategory": "student", "nationality": "Test nationality",
                "gender": "undisclosed", "dateOfBirth": "2000-01-01",
                "currentCountry": "Test country", "currentCity": "Test city"}})
        assert onboarding.status == 200, await onboarding.text()
        assert (await onboarding.json())["data"]["completed"], await onboarding.text()
        message = await api.post("http://backend:8000/v1/events", headers=origin, data={
            "network": workspace, "type": "workspace.message.posted",
            "target": "channel/pai-counselor", "payload": {"content": "I finished school."},
            "metadata": {"target_agents": ["pai"]}})
        assert message.status == 200, await message.text()
        events = await api.get(f"http://backend:8000/v1/events?network={workspace}&channel=pai-counselor")
        assert events.status == 200, await events.text()
        event_text = await events.text()
        assert "What did you enjoy most about your studies?" in event_text, event_text
        voice = await api.post("http://backend:8000/v1/counselor/voice/session", headers=origin,
                               data={"network": workspace, "conversation": "pai-counselor",
                                     "sdp": "v=0\r\ns=offline student offer\r\n"})
        assert voice.status == 200, await voice.text()
        assert (await voice.json())["data"]["session_id"] == "offline-voice-session"
        roadmaps = await api.get(f"http://backend:8000/v1/roadmaps?network={workspace}")
        assert roadmaps.status == 200, await roadmaps.text()
        cookies = await context.cookies()
        for cookie in cookies:
            if cookie["name"] == "pai_session":
                cookie["domain"] = "localhost"
                await context.add_cookies([cookie])

        async def forward(route):
            url = route.request.url
            if url.startswith("http://localhost:13000"):
                response = await route.fetch(url=url.replace("http://localhost:13000", "http://frontend:3000", 1))
                await route.fulfill(response=response)
            elif url.startswith("http://localhost:18000"):
                if "/events/stream" in url:
                    await route.abort()
                    return
                response = await route.fetch(url=url.replace("http://localhost:18000", "http://backend:8000", 1))
                await route.fulfill(response=response)
            else:
                # Permit no third-party analytics, identity or model requests.
                await route.abort()

        await context.route("**/*", forward)
        page = await context.new_page()
        response = await page.goto(f"http://localhost:13000/{workspace}?view=roadmaps")
        assert response.status == 200
        try:
            await page.get_by_role("heading", name="Roadmaps", exact=True, level=1).wait_for(timeout=45000)
        except Exception:
            print(json.dumps({"page_url": page.url, "body": await page.locator("body").inner_text()}))
            raise
        body = await page.locator("body").inner_text()
        assert "Could not load roadmaps" not in body
        print(json.dumps({"login": "passed (fake provider, real PAI session)",
                          "chat": "passed (fake model, real event pipeline)",
                          "voice_route": "passed (fake SDP handshake, not live audio)",
                          "roadmaps_api": roadmaps.status, "roadmaps_browser": "passed"}))
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
