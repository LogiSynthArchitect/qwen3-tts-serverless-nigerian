import asyncio, os
from vastai import Serverless

async def main():
    c = Serverless(api_key=os.environ.get("VAST_API_KEY"))
    for route in ["/api/v0/credits/", "/api/v0/me/", "/api/v0/users/me/"]:
        try:
            r = await c._make_request(
                client=c, url=c.vast_web_url, route=route,
                api_key=[REDACTED]"VAST_API_KEY"), method="GET")
            print(route, "->", str(r)[:300])
        except Exception as e:
            print(route, "ERR", str(e)[:140])

asyncio.run(main())
