"""Browser/API smoke check against docker-compose.offline.yml; no model APIs.

Run in the existing browser backend image on pai-consolidation-check_host_access.
It drives the API with the offline startup app's stand-in Firebase token.
"""

import asyncio
import json

from playwright.async_api import async_playwright


async def main():
    async with async_playwright() as playwright:
        api = await playwright.request.new_context()
        # Every call carries the (fake, offline) Firebase ID token as its bearer.
        auth = {"Authorization": "Bearer offline-provider-token"}
        login = await api.post("http://backend:8000/v1/auth/session", headers=auth,
                               data={"deviceId": "offline-startup-check"})
        assert login.status == 200, await login.text()
        workspace = (await login.json())["data"]["workspace"]["workspaceId"]
        onboarding = await api.post(
            f"http://backend:8000/v1/student-profile/onboarding?network={workspace}",
            headers=auth, data={"answers": {
                "fullName": "Offline Student", "preferredName": "Student",
                "statusCategory": "student", "nationality": "Test nationality",
                "gender": "undisclosed", "dateOfBirth": "2000-01-01",
                "currentCountry": "Test country", "currentCity": "Test city"}})
        assert onboarding.status == 200, await onboarding.text()
        assert (await onboarding.json())["data"]["completed"], await onboarding.text()
        message = await api.post("http://backend:8000/v1/events", headers=auth, data={
            "network": workspace, "type": "workspace.message.posted",
            "target": "channel/pai-counselor", "payload": {"content": "I finished school."},
            "metadata": {"target_agents": ["pai"]}})
        assert message.status == 200, await message.text()
        events = await api.get(f"http://backend:8000/v1/events?network={workspace}&channel=pai-counselor",
                               headers=auth)
        assert events.status == 200, await events.text()
        event_text = await events.text()
        assert "What did you enjoy most about your studies?" in event_text, event_text
        voice = await api.post("http://backend:8000/v1/counselor/voice/session", headers=auth,
                               data={"network": workspace, "conversation": "pai-counselor",
                                     "sdp": "v=0\r\ns=offline student offer\r\n"})
        assert voice.status == 200, await voice.text()
        assert (await voice.json())["data"]["session_id"] == "offline-voice-session"
        roadmaps = await api.get(f"http://backend:8000/v1/roadmaps?network={workspace}", headers=auth)
        assert roadmaps.status == 200, await roadmaps.text()
        print(json.dumps({"login": "passed (fake Firebase token, real account and device record)",
                          "chat": "passed (fake model, real event pipeline)",
                          "voice_route": "passed (fake SDP handshake, not live audio)",
                          "roadmaps_api": roadmaps.status}))
        await api.dispose()


if __name__ == "__main__":
    asyncio.run(main())
