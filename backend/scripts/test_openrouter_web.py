import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.research.providers.openrouter.client import OpenRouterClient


async def main() -> None:
    client = OpenRouterClient(get_settings())
    response = await client.create_completion(
        messages=[
            {
                "role": "user",
                "content": (
                    "Use live web search to find the current UTC date and time "
                    "from an online source. Return the time and source URL."
                ),
            }
        ],
        tools=[{"type": "openrouter:web_search"}],
    )
    print(response.choices[0].message.content)


if __name__ == "__main__":
    asyncio.run(main())
