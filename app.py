from time import sleep
from os import listdir

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

# list of ids of users with jingles
jingle_ids: list[int] = []
for jingle in listdir("jingles"):
    jingle_ids.append(int(jingle.split(".")[0]))


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")


# play jingle when specific users join VC
@bot.event
async def on_voice_state_update(
    member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
):
    if (
        member.id in jingle_ids
        and before.channel != after.channel
        and after.channel
        and not 1091566578425921626 in after.channel.voice_states
    ):
        vc = await after.channel.connect()
        vc.play(discord.FFmpegOpusAudio(source=f"jingles/{member.id}.opus"))
        while vc.is_playing():
            sleep(0.1)
        await vc.disconnect()


bot.run(secret.api_key)
