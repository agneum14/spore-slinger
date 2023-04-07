from time import sleep
from os import listdir

import discord
from discord.commands import option
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

# misc
cats = ["cubensis", "albino cubensis", "other psylocybe", "panaelous", "gourmet"]
cat_descs = [
    "Psilocybe Cubensis",
    "Albino Psilocybe Cubensis",
    "Other Psolocybes",
    "Panaelous",
    "Gourmet",
]


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")


# default response to avoid interaction failure
async def canned_respond(ctx: discord.ApplicationContext):
    if not ctx.channel or ctx.channel.type is not discord.ChannelType.private:
        await ctx.respond("DM'd 😏")
    else:
        await ctx.respond(
            "Sterile technique is for nerds. I spit on my plates.", delete_after=0
        )


# get strains in given category
get_cat_strains = lambda category: scol.find({"category": category}).sort("name", 1)


# add new trader if ID not in category
def assert_trader(sid: int):
    trader = tcol.find_one({"_id": sid})
    if not trader:
        data = {"_id": sid, "strains": [], "whitelist": [], "whitelist_enabled": False}
        tcol.insert_one(data)
        trader = tcol.find_one({"_id": sid})

    return trader


# /find: see who has a certain strain
@bot.application_command(description="See who got what you want")
async def find(ctx: discord.ApplicationContext, strain: str):
    await canned_respond(ctx)

    sid = scol.find_one({"name": strain})["_id"]  # type: ignore
    trader_docs = tcol.find({"strains": {"$eq": sid}})

    tags = []
    for trader_doc in trader_docs:
        trader_id = trader_doc["_id"]
        user: discord.User = await bot.fetch_user(trader_id)
        tag = f"{user.name}#{user.discriminator}"
        tags.append(tag)

    if len(tags) == 0:
        await ctx.author.send(f"Nobody has {strain}. Tough luck bud!")
    else:
        msg = f"**{strain} is stocked by:**\n"
        for tag in tags:
            msg += f"{tag}\n"
        await ctx.author.send(msg[:-1])


# /compare: compare user's library with a parameterized user
@bot.application_command(description="Compare your library to another gamer's")
async def compare(ctx: discord.ApplicationContext, mbr: discord.Member):
    await canned_respond(ctx)

    astrain_ids = tcol.find_one({"_id": ctx.author.id}, {"strains": 1})
    mstrain_ids = tcol.find_one({"_id": mbr.id}, {"strains": 1})
    if not astrain_ids or not mstrain_ids:
        await ctx.author.send(
            "Comparison disallowed: one of you hasn't set up your library!\nUse /edit"
        )
        return

    astrain_ids = astrain_ids["strains"]  # type: ignore
    mstrain_ids = mstrain_ids["strains"]  # type: ignore
    # get strain ids unique to author and mber
    auniq_ids = list(set(astrain_ids) - set(mstrain_ids))
    muniq_ids = list(set(mstrain_ids) - set(astrain_ids))

    def add_names(ids):
        msg = ""
        names = []

        for sid in ids:
            names.append(scol.find_one({"_id": sid})["name"])  # type: ignore
        names.sort()
        for name in names:
            msg += f"{name}\n"

        return msg

    msg = f"**Strains {mbr.name} has that you don't:**\n"
    msg += add_names(muniq_ids)
    msg += f"**Strains you have that {mbr.name} doesn't:**\n"
    msg += add_names(auniq_ids)

    await ctx.author.send(msg[:-1])


# Button subclass for /edit command
class EditButton(discord.ui.Button):
    def __init__(self, label, style, sid, trader):
        super().__init__(style=style, label=label)
        self.sid = sid
        self.tid = trader["_id"]
        self.tstrains = trader["strains"]

    async def callback(self, interaction):
        await interaction.response.defer()

        if self.sid in self.tstrains:
            self.tstrains.remove(self.sid)
            self.style = discord.ButtonStyle.red
            tcol.update_one({"_id": self.tid}, {"$set": {"strains": self.tstrains}})
        else:
            self.tstrains.append(self.sid)
            self.style = discord.ButtonStyle.green
            tcol.update_one({"_id": self.tid}, {"$set": {"strains": self.tstrains}})

        await interaction.edit_original_response(view=self.view)


# /edit: user edits their strain list via clickable buttons
@bot.application_command(description="Edit your inventory, like a lewd MMORPG")
async def edit(ctx: discord.ApplicationContext):
    await canned_respond(ctx)

    cat_views = []
    trader = assert_trader(ctx.author.id)

    for cat in cats:
        views: list[discord.ui.View] = []

        view = discord.ui.View()
        for i, strain in enumerate(get_cat_strains(cat)):
            if i % 25 == 0 and i != 0:
                views.append(view)
                view = discord.ui.View()

            label = strain["name"]  # type: ignore
            style = (
                discord.ButtonStyle.green
                if strain["_id"] in trader["strains"]  # type: ignore
                else discord.ButtonStyle.red
            )
            strain_id = strain["_id"]
            button = EditButton(label, style, strain_id, trader)
            view.add_item(button)
        views.append(view)

        cat_views.append(views)

    async def send_cat_buttons(desc, cat_view):
        await ctx.author.send(f"**{desc}**")
        for view in cat_view:
            await ctx.author.send(view=view)

    await ctx.author.send("**BE PATIENT: DISCORD LIMITS MESSAGE FREQUENCY**")
    for desc, cat_view in zip(cat_descs, cat_views):
        await send_cat_buttons(desc, cat_view)


# /handled: list currently handled strains
@bot.application_command(description="List strains currently handled by Spore Slinger")
async def handled(ctx: discord.ApplicationContext):
    await canned_respond(ctx)

    def get_cat_msg(descriptor, category):
        msg = f"**{descriptor}**\n"

        for strain in get_cat_strains(category):
            name = strain["name"]
            msg += f"{name}\n"

        return msg

    msg = "**CURRENTLY HANDLED STRAINS:**\n"
    for desc, cat in zip(cat_descs, cats):
        msg += get_cat_msg(desc, cat)

    await ctx.author.send(msg[:-1])


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
