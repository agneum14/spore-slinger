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


# get strains in given category
get_cat_strains = lambda category: scol.find({"category": category}).sort("name", 1)


# get author document or False with message
async def get_auth_tdoc(ctx: discord.ApplicationContext):
    if tdoc := tcol.find_one({"_id": ctx.author.id}):
        return tdoc
    await ctx.send_response(
        "You don't have a library! Create it with /edit", ephemeral=True
    )
    return False


# return if author is whitelisted by member
def is_whitelisted(aid: int, mid: int) -> bool:
    mdoc = tcol.find_one({"_id": mid}, {"whitelist": 1, "whitelist_enabled": 1})
    if not mdoc:
        return False
    wl = mdoc["whitelist"]
    wle = mdoc["whitelist_enabled"]

    if wle and aid is not mid and not aid in wl:
        return False
    return True


# group for whitelist commands
whitelist = bot.create_group("whitelist", "Alter and check your whitelist")


# Select subclass for /whitelist remove command
class WhiteListRemoveSelect(discord.ui.Select):
    def __init__(self, options, aid, names, wl) -> None:
        super().__init__(
            placeholder="Select users",
            min_values=0,
            max_values=len(options),
            options=options,
        )
        self.aid: int = aid
        self.names: list[str] = names
        self.wl: list[int] = wl

    async def callback(self, interaction):
        # await interaction.response.defer()

        for name in self._selected_values:
            i = self.names.index(name)
            self.names.pop(i)
            self.wl.pop(i)
        tcol.update_one({"_id": self.aid}, {"$set": {"whitelist": self.wl}})

        await interaction.response.send_message(
            "Removed selected users.", ephemeral=True
        )


# /whitelist remove: create Select menu to remove users from whitelist
@whitelist.command(description="Remove users from your whitelist")
async def remove(ctx: discord.ApplicationContext):
    if not [tdoc := await get_auth_tdoc(ctx)]:
        return
    wl = tdoc["whitelist"]  # type: ignore
    if len(wl) == 0:
        await ctx.send_response(
            "You don't have anyone on your whitelist!", ephemeral=True
        )
        return

    names: list[str] = list()
    options: list[discord.SelectOption] = list()
    for uid in wl:
        user = await bot.fetch_user(uid)
        name = user.name
        names.append(name)
        option = discord.SelectOption(label=name)
        options.append(option)

    select = WhiteListRemoveSelect(options, ctx.author.id, names, wl)
    view = discord.ui.View()
    view.add_item(select)

    await ctx.send_response(view=view, ephemeral=True)


# /whitelist view: print whitelist status and users
@whitelist.command(description="View your whitelist")
async def view(ctx: discord.ApplicationContext):
    if not [tdoc := await get_auth_tdoc(ctx)]:
        return
    wle = tdoc["whitelist_enabled"]  # type: ignore
    wl = tdoc["whitelist"]  # type: ignore

    msg = f"Whitelist status: {wle}\nTrusted users:\n"
    for uid in wl:
        user = await bot.fetch_user(uid)
        msg += f"{user.name}\n"

    await ctx.send_response(msg[:-1], ephemeral=True)


# /whitelist add: add given user to author's whitelist
@whitelist.command(description="Add a user to your whitelist")
async def add(ctx: discord.ApplicationContext, mbr: discord.Member):
    if not [tdoc := await get_auth_tdoc(ctx)]:
        return

    wl: list[int] = tdoc["whitelist"]  # type: ignore
    if not mbr.id in wl:
        wl.append(mbr.id)
        tcol.update_one({"_id": ctx.author.id}, {"$set": {"whitelist": wl}})

    await ctx.send_response(f"Added {mbr.name} to your whitelist!", ephemeral=True)


# /whitelist toggle: enable/disable author's whitelist
@whitelist.command(description="Toggle your whitelist")
async def toggle(ctx: discord.ApplicationContext):
    if not [tdoc := await get_auth_tdoc(ctx)]:
        return

    if tdoc["whitelist_enabled"]:  # type: ignore
        tcol.update_one({"_id": ctx.author.id}, {"$set": {"whitelist_enabled": False}})
        await ctx.send_response("Your whitelist has been *disabled*!", ephemeral=True)
    else:
        tcol.update_one({"_id": ctx.author.id}, {"$set": {"whitelist_enabled": True}})
        await ctx.send_response("Your whitelist has been *enabled*!", ephemeral=True)


# /peek: print library of given user
@bot.application_command(description="Peek user's library")
async def peek(ctx: discord.ApplicationContext, mbr: discord.Member):
    tdoc = tcol.find_one({"_id": mbr.id})
    if not tdoc:
        await ctx.send_response(
            f"Peek disallowed: {mbr.name} has no library!", ephemeral=True
        )
        return
    if not is_whitelisted(ctx.author.id, mbr.id):
        await ctx.send_response(
            f"Peek disallowed: you're not on {mbr.name}'s whitelist!", ephemeral=True
        )
        return

    msg = f"**{mbr.name}'s library:\n**"
    strain_ids = tdoc["strains"]  # type: ignore
    for sid in strain_ids:
        name = scol.find_one({"_id": sid})["name"]  # type: ignore
        msg += f"{name}\n"

    await ctx.send_response(msg, ephemeral=True)


# /find: see who has a certain strain
@bot.application_command(description="See who got what you want")
async def find(ctx: discord.ApplicationContext, strain: str):
    sid = scol.find_one({"name": strain})["_id"]  # type: ignore
    trader_docs = tcol.find({"strains": {"$eq": sid}})

    tags = []
    for trader_doc in trader_docs:
        trader_id = trader_doc["_id"]
        if not is_whitelisted(ctx.author.id, trader_id):
            continue
        user: discord.User = await bot.fetch_user(trader_id)
        tag = f"{user.name}#{user.discriminator}"
        tags.append(tag)

    if len(tags) == 0:
        await ctx.send_response(f"Nobody has {strain}. Tough luck bud!", ephemeral=True)
    else:
        msg = f"**{strain} is stocked by:**\n"
        for tag in tags:
            msg += f"{tag}\n"
        await ctx.send_response(msg[:-1], ephemeral=True)


# /compare: compare user's library with a parameterized user
@bot.application_command(description="Compare your library to another gamer's")
async def compare(ctx: discord.ApplicationContext, mbr: discord.Member):
    astrain_ids = tcol.find_one({"_id": ctx.author.id}, {"strains": 1})
    mstrain_ids = tcol.find_one({"_id": mbr.id}, {"strains": 1})
    if not astrain_ids or not mstrain_ids:
        await ctx.send_response(
            "Comparison disallowed: one of you hasn't set up your library!\nUse /edit",
            ephemeral=True,
        )
        return
    if not is_whitelisted(ctx.author.id, mbr.id):
        await ctx.send_response(
            f"Comparison disallowed: you're not on {mbr.name}'s whitelist!",
            ephemeral=True,
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

    await ctx.send_response(msg[:-1], ephemeral=True)


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
    # add new trader if ID not in category
    def assert_trader(sid: int):
        trader = tcol.find_one({"_id": sid})
        if not trader:
            data = {
                "_id": sid,
                "strains": [],
                "whitelist": [],
                "whitelist_enabled": False,
            }
            tcol.insert_one(data)
            trader = tcol.find_one({"_id": sid})

        return trader

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
        desc = desc.upper()
        await ctx.send_followup(f"**{desc}**")
        for view in cat_view:
            await ctx.send_followup(view=view, ephemeral=True)

    await ctx.send_response(
        "Click the buttons to add/remove strains in your library", ephemeral=True
    )
    for desc, cat_view in zip(cat_descs, cat_views):
        await send_cat_buttons(desc, cat_view)


# /handled: list currently handled strains
@bot.application_command(description="List strains currently handled by Spore Slinger")
async def handled(ctx: discord.ApplicationContext):
    def get_cat_msg(descriptor, category):
        msg = f"**{descriptor}**\n"

        for strain in get_cat_strains(category):
            name = strain["name"]
            msg += f"{name}\n"

        return msg

    msg = "**CURRENTLY HANDLED STRAINS:**\n"
    for desc, cat in zip(cat_descs, cats):
        msg += get_cat_msg(desc, cat)

    await ctx.send_response(msg[:-1], ephemeral=True)


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
