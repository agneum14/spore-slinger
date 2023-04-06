import discord
from discord.ext import commands
import pymongo

import secret

# bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
bot = commands.Bot(intents=intents)

# db setup
mongo_client = pymongo.MongoClient(secret.mongodb_url)
db = mongo_client["spore_slinger"]
scol = db["strains"]
tcol = db["traders"]


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")


bot.run(secret.api_key)
