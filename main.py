import asyncio
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv(override=True)

from sky_bot import MentionableTree, SkyBot

if os.name == "nt":
    policy = asyncio.WindowsSelectorEventLoopPolicy()
    asyncio.set_event_loop_policy(policy)


async def main():
    token = os.getenv("SKYBOT_TOKEN")
    if token is None:
        raise Exception("Please add your token to .env file.")

    intents = discord.Intents.default()
    intents.members = True
    intents.message_content = True

    initial_extensions = [
        "emoji_manager",
        "info",
        "tools",
        "welcome",
        "role_manager",
        "sky_events",
    ]

    bot = SkyBot(
        commands.when_mentioned_or("!"),
        initial_extensions=initial_extensions,
        intents=intents,
        tree_cls=MentionableTree,
        proxy=os.getenv("PROXY"),
    )

    async with bot:
        try:
            await bot.start(token)
        except discord.HTTPException as e:
            if e.status == 429:
                print(
                    "The Discord servers denied the connection for making too many requests"
                )
                print(
                    "Get help from https://stackoverflow.com/questions/66724687/in-discord-py-how-to-solve-the-error-for-toomanyrequests"
                )
            else:
                raise e


if __name__ == "__main__":
    asyncio.run(main())
