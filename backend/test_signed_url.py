import asyncio
from app.services import storage_service
from app.config import get_settings

async def main():
    try:
        url = storage_service.create_signed_url("some_fake_url", "test-bucket")
        print("Success:", url)
    except Exception as e:
        print("Error:", repr(e))

asyncio.run(main())
