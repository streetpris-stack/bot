"""
╔══════════════════════════════════════════════════════════════════╗
║                        NBots — bot.py                            ║
║  Modération · Anti-Raid · Antispam · Tickets · Logs              ║
║  Giveaway · Rolemenu · TempVoc · Invites · Compteurs · Jeux      ║
║  WL/BL · Permissions par rôle · Welcome avancé · Tickets Pro     ║
╚══════════════════════════════════════════════════════════════════╝

Dépendances :
    pip install discord.py

Lancement :
    1. Mets ton token dans config.json  →  "token": "TON_TOKEN"
    2. python bot.py
"""

# ════════════════════════════════════════════════════════════════════
#  IMPORTS
# ════════════════════════════════════════════════════════════════════
import discord
from discord.ext import commands, tasks
from discord import app_commands

import asyncio, json, os, random, re, time, logging
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from pathlib import Path

# ════════════════════════════════════════════════════════════════════
#  LOGGING
# ════════════════════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("bot.log", encoding="utf-8"), logging.StreamHandler()]
)
log = logging.getLogger("NBots")

# ════════════════════════════════════════════════════════════════════
#  CONFIG + BASE DE DONNÉES JSON
# ════════════════════════════════════════════════════════════════════
CONFIG_FILE = "config.json"
DATA_DIR    = Path("data")
DATA_DIR.mkdir(exist_ok=True)

DEFAULT_CONFIG = {
    "token"  : "MTM4Nzk3OTI1OTYxMTU3ODQ3OQ.GA46-D.41z5o04MeovNyDHPgBurF9SZhqs5LD9J7RjDI0",
    "prefix" : "+",
    "bot_name": "NBots",
    "color"         : 0x5865F2,
    "success_color" : 0x2ecc71,
    "error_color"   : 0xe74c3c,
    "warn_color"    : 0xf1c40f,
    "owner_ids": [],
    "mod_log_channel": None,
    "antiraid": {
        "enabled"           : True,
        "join_rate"         : 8,
        "join_interval"     : 8,
        "action"            : "kick",
        "new_account_days"  : 7,
        "new_account_action": "kick",
        "lockdown_auto"     : True
    },
    "antispam": {
        "enabled"        : True,
        "msg_limit"      : 5,
        "interval"       : 4,
        "action"         : "mute",
        "mute_minutes"   : 10,
        "ignore_roles"   : [],
        "ignore_channels": []
    },
    "welcome": {
        "enabled"       : False,
        "channel"       : None,
        "message"       : "Bienvenue {mention} sur **{server}** !",
        "role"          : None,
        "show_avatar"   : True,
        "show_inviter"  : True,
        "background_color": 0x2C2F33
    },
    "goodbye": {
        "enabled": False,
        "channel": None,
        "message": "Au revoir **{name}** ! 👋"
    },
    # Permissions par rôle : { "role_id": ["cmd1", "cmd2", ...] }
    "role_permissions": {},
    # Whitelist globale : liste d'IDs utilisateurs autorisés à tout faire
    "whitelist": [],
    # Blacklist globale : liste d'IDs utilisateurs bloqués
    "blacklist": []
}

def load_config() -> dict:
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)
        log.warning("config.json créé — remplis ton token !")
    with open(CONFIG_FILE) as f:
        data = json.load(f)
    # S'assurer que les nouvelles clés existent
    for key in ("role_permissions", "whitelist", "blacklist"):
        if key not in data:
            data[key] = DEFAULT_CONFIG[key]
    if "bot_name" not in data:
        data["bot_name"] = "NBots"
    return data

def save_config(cfg: dict):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

cfg = load_config()

# ─── Helpers JSON ────────────────────────────────────────────────
def _path(name): return DATA_DIR / f"{name}.json"

def db_load(name: str) -> dict:
    p = _path(name)
    if p.exists():
        with open(p) as f:
            return json.load(f)
    return {}

def db_save(name: str, data: dict):
    with open(_path(name), "w") as f:
        json.dump(data, f, indent=2)

def db_get(name, guild_id, default=None):
    return db_load(name).get(str(guild_id), default if default is not None else {})

def db_set(name, guild_id, value):
    d = db_load(name); d[str(guild_id)] = value; db_save(name, d)

# ─── Embed helpers ───────────────────────────────────────────────
def em(description=None, *, title=None, color=None) -> discord.Embed:
    return discord.Embed(
        description=description, title=title,
        color=color or cfg["color"],
        timestamp=datetime.now(timezone.utc)
    )

def ok(msg):   return em(f"✅ {msg}", color=cfg["success_color"])
def err(msg):  return em(f"❌ {msg}", color=cfg["error_color"])
def warn(msg): return em(f"⚠️ {msg}", color=cfg["warn_color"])

async def send_log(guild: discord.Guild, embed: discord.Embed):
    cid = cfg.get("mod_log_channel")
    if cid:
        ch = guild.get_channel(int(cid))
        if ch:
            try: await ch.send(embed=embed)
            except: pass

def parse_duration(text: str):
    """'10m' -> 600 | '2h' -> 7200 | '30s' -> 30 | None si invalide"""
    m = re.fullmatch(r"(\d+)(s|m|h|d)", text.strip().lower())
    if not m: return None
    v, u = int(m.group(1)), m.group(2)
    return v * {"s": 1, "m": 60, "h": 3600, "d": 86400}[u]

# ════════════════════════════════════════════════════════════════════
#  SYSTÈME WHITELIST / BLACKLIST / PERMISSIONS PAR RÔLE
# ════════════════════════════════════════════════════════════════════

def is_blacklisted(user_id: int) -> bool:
    return user_id in [int(x) for x in cfg.get("blacklist", [])]

def is_whitelisted(user_id: int) -> bool:
    return user_id in [int(x) for x in cfg.get("whitelist", [])]

def has_role_permission(member: discord.Member, command_name: str) -> bool:
    """Vérifie si un rôle du membre a accès à la commande."""
    if member.guild_permissions.administrator:
        return True
    if is_whitelisted(member.id):
        return True
    role_perms = cfg.get("role_permissions", {})
    for role in member.roles:
        allowed = role_perms.get(str(role.id), [])
        if "*" in allowed or command_name in allowed:
            return True
    return False

def wl_check(cmd_name: str = None):
    """Check combiné : pas blacklisté + permission rôle (si cmd_name fourni)."""
    async def predicate(ctx):
        if is_blacklisted(ctx.author.id):
            await ctx.send(embed=err("Tu es blacklisté et ne peux pas utiliser ce bot."), delete_after=5)
            return False
        if cmd_name and not has_role_permission(ctx.author, cmd_name):
            # laisser passer si la commande n'est pas dans la config (comportement par défaut)
            role_perms = cfg.get("role_permissions", {})
            all_restricted = any(cmd_name in v for v in role_perms.values())
            if all_restricted:
                await ctx.send(embed=err("Ton rôle n'a pas accès à cette commande."), delete_after=5)
                return False
        return True
    return commands.check(predicate)

# ════════════════════════════════════════════════════════════════════
#  BOT
# ════════════════════════════════════════════════════════════════════
intents = discord.Intents.all()

class NBots(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=commands.when_mentioned_or(cfg["prefix"]),
            intents=intents,
            help_command=None,
            case_insensitive=True,
        )
        self.spam_tracker: dict[int, dict[int, list]]  = defaultdict(lambda: defaultdict(list))
        self.raid_tracker:  dict[int, list]             = defaultdict(list)
        self.lockdown_guilds: set[int]                  = set()

    async def setup_hook(self):
        await self.tree.sync()

    async def on_ready(self):
        bot_name = cfg.get("bot_name", "NBots")
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name=f"{len(self.guilds)} serveurs | {cfg['prefix']}help"
            )
        )
        log.info(f"Connecté : {self.user} ({len(self.guilds)} serveurs)")
        # Cacher les invites actuelles
        for guild in self.guilds:
            try:
                invites = await guild.invites()
                invite_cache[guild.id] = {inv.code: inv.uses for inv in invites}
            except: pass
        if not update_counters.is_running():
            update_counters.start()
        if not check_giveaways.is_running():
            check_giveaways.start()
        print(f"""
╔══════════════════════════════════════╗
║      ✅  {bot_name} est en ligne !
║  Tag     : {self.user}
║  Serveurs: {len(self.guilds)}
║  Préfixe : {cfg['prefix']}
╚══════════════════════════════════════╝""")

    # ─── EVENTS GLOBAUX ──────────────────────────────────────────

    async def on_member_join(self, member: discord.Member):
        await _check_raid(member)
        await _check_new_account(member)
        await _do_welcome(member)
        await _track_invite(member)

    async def on_member_remove(self, member: discord.Member):
        await _do_goodbye(member)

    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        # Bloquer les blacklistés
        if is_blacklisted(message.author.id):
            return
        await _check_spam(message)
        await _check_invite_filter(message)
        await _run_automod(message)
        await _run_custom_cmd(message)
        await self.process_commands(message)

    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(embed=err("Tu n'as pas les permissions requises."), delete_after=6)
        elif isinstance(error, commands.MemberNotFound):
            await ctx.send(embed=err("Membre introuvable."), delete_after=6)
        elif isinstance(error, commands.CommandNotFound):
            pass
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(embed=err(f"Argument manquant : `{error.param.name}`"), delete_after=6)
        elif isinstance(error, commands.CheckFailure):
            pass  # Déjà géré dans les checks
        else:
            log.error(f"Erreur commande : {error}")

    async def on_voice_state_update(self, member, before, after):
        await _tempvoc_handler(member, before, after)

    async def on_message_delete(self, message):
        if message.author.bot or not message.guild: return
        e = em(
            f"💬 Message supprimé dans {message.channel.mention}\n"
            f"**{message.author}** : {message.content[:500] or '*[embed/fichier]*'}",
            color=cfg["warn_color"]
        )
        await send_log(message.guild, e)

    async def on_message_edit(self, before, after):
        if before.author.bot or not before.guild: return
        if before.content == after.content: return
        e = em(color=cfg["color"], title="✏️ Message modifié")
        e.add_field(name="Avant", value=before.content[:400] or "*vide*", inline=False)
        e.add_field(name="Après", value=after.content[:400] or "*vide*", inline=False)
        e.set_footer(text=f"{before.author} | #{before.channel}")
        await send_log(before.guild, e)

    async def on_member_ban(self, guild, user):
        e = em(f"🔨 **{user}** a été banni.", color=cfg["error_color"])
        await send_log(guild, e)

    async def on_member_unban(self, guild, user):
        e = em(f"✅ **{user}** a été débanni.", color=cfg["success_color"])
        await send_log(guild, e)

    async def on_invite_create(self, invite):
        invite_cache.setdefault(invite.guild.id, {})[invite.code] = invite.uses


bot = NBots()

# ════════════════════════════════════════════════════════════════════
#  CHECKS
# ════════════════════════════════════════════════════════════════════
def is_mod():
    async def predicate(ctx):
        if is_blacklisted(ctx.author.id): return False
        return (ctx.author.guild_permissions.manage_messages or
                ctx.author.guild_permissions.administrator or
                is_whitelisted(ctx.author.id))
    return commands.check(predicate)

def is_admin():
    async def predicate(ctx):
        if is_blacklisted(ctx.author.id): return False
        return (ctx.author.guild_permissions.administrator or
                is_whitelisted(ctx.author.id))
    return commands.check(predicate)

# ════════════════════════════════════════════════════════════════════
#  ANTI-RAID
# ════════════════════════════════════════════════════════════════════
async def _check_raid(member: discord.Member):
    if not cfg["antiraid"]["enabled"]: return
    conf = cfg["antiraid"]
    gid = member.guild.id
    now = time.time()
    bot.raid_tracker[gid] = [t for t in bot.raid_tracker[gid] if now - t < conf["join_interval"]]
    bot.raid_tracker[gid].append(now)
    if len(bot.raid_tracker[gid]) >= conf["join_rate"]:
        await _antiraid_action(member, "flood de joins détecté")
        if conf.get("lockdown_auto") and gid not in bot.lockdown_guilds:
            bot.lockdown_guilds.add(gid)
            await send_log(member.guild,
                em("🔒 **LOCKDOWN AUTO** activé suite à un raid !", color=cfg["error_color"]))

async def _check_new_account(member: discord.Member):
    if not cfg["antiraid"]["enabled"]: return
    days = cfg["antiraid"]["new_account_days"]
    age = (datetime.now(timezone.utc) - member.created_at).days
    if age < days:
        await _antiraid_action(member, f"compte trop récent ({age}j < {days}j)")

async def _antiraid_action(member: discord.Member, reason: str):
    action = cfg["antiraid"]["action"]
    e = em(f"🛡️ **Anti-Raid** | `{member}` → `{action}` — {reason}", color=cfg["error_color"])
    await send_log(member.guild, e)
    try:
        if action == "kick":    await member.kick(reason=reason)
        elif action == "ban":   await member.ban(reason=reason)
        elif action == "timeout":
            await member.timeout(timedelta(hours=1), reason=reason)
    except: pass

# ════════════════════════════════════════════════════════════════════
#  ANTISPAM
# ════════════════════════════════════════════════════════════════════
async def _check_spam(message: discord.Message):
    if not cfg["antispam"]["enabled"]: return
    conf = cfg["antispam"]
    member = message.author
    if any(r.id in conf["ignore_roles"] for r in member.roles): return
    if message.channel.id in conf["ignore_channels"]: return
    gid, uid, now = message.guild.id, member.id, time.time()
    history = bot.spam_tracker[gid][uid]
    history = [t for t in history if now - t < conf["interval"]]
    history.append(now)
    bot.spam_tracker[gid][uid] = history
    if len(history) >= conf["msg_limit"]:
        bot.spam_tracker[gid][uid] = []
        await _antispam_action(message)

async def _antispam_action(message: discord.Message):
    action = cfg["antispam"]["action"]
    member = message.author
    try: await message.delete()
    except: pass
    reason = "Spam détecté"
    if action == "mute":
        mins = cfg["antispam"]["mute_minutes"]
        try: await member.timeout(timedelta(minutes=mins), reason=reason)
        except: pass
        await message.channel.send(
            embed=warn(f"{member.mention} a été mis en sourdine {mins}min pour spam."),
            delete_after=5)
    elif action == "kick":
        try: await member.kick(reason=reason)
        except: pass
    elif action == "ban":
        try: await member.ban(reason=reason)
        except: pass
    await send_log(message.guild,
        em(f"🚫 **Antispam** | `{member}` → `{action}`", color=cfg["warn_color"]))

# ════════════════════════════════════════════════════════════════════
#  FILTRE INVITATIONS + AUTOMOD
# ════════════════════════════════════════════════════════════════════
async def _check_invite_filter(message: discord.Message):
    data = db_get("invite_filter", message.guild.id)
    if not data.get("enabled"): return
    if re.search(r"discord\.gg/\S+", message.content, re.I):
        try: await message.delete()
        except: pass
        await message.channel.send(
            embed=warn(f"{message.author.mention}, les invitations sont interdites ici."),
            delete_after=5)

async def _run_automod(message: discord.Message):
    data = db_get("automod", message.guild.id)
    if not data.get("enabled") or not data.get("words"): return
    content = message.content.lower()
    for word in data["words"]:
        if word.lower() in content:
            try: await message.delete()
            except: pass
            await message.channel.send(
                embed=warn(f"{message.author.mention}, ce message contient un mot interdit."),
                delete_after=5)
            return

# ════════════════════════════════════════════════════════════════════
#  WELCOME AVANCÉ (style screen)
# ════════════════════════════════════════════════════════════════════
invite_cache: dict[int, dict] = {}
join_inviter_cache: dict[int, dict] = {}   # guild_id -> { member_id: inviter_id }

async def _do_welcome(member: discord.Member):
    wcfg = cfg["welcome"]
    if not wcfg["enabled"] or not wcfg["channel"]: return
    ch = member.guild.get_channel(int(wcfg["channel"]))
    if not ch: return

    # Trouver l'inviteur
    inviter = None
    try:
        new_invites = await member.guild.invites()
        old = invite_cache.get(member.guild.id, {})
        for inv in new_invites:
            if old.get(inv.code, 0) < inv.uses:
                inviter = inv.inviter
                break
        invite_cache[member.guild.id] = {inv.code: inv.uses for inv in new_invites}
    except: pass

    # Âge du compte
    account_age = (datetime.now(timezone.utc) - member.created_at).days
    account_age_str = f"{account_age} jour(s)"
    if account_age >= 365:
        account_age_str = f"{account_age // 365} an(s)"

    # Nombre de fois qu'il a rejoint
    join_history = db_get("join_history", member.guild.id)
    uid = str(member.id)
    join_history.setdefault(uid, 0)
    join_history[uid] += 1
    db_set("join_history", member.guild.id, join_history)
    join_count = join_history[uid]

    # Construire l'embed riche
    e = discord.Embed(color=wcfg.get("background_color", 0x2C2F33),
                      timestamp=datetime.now(timezone.utc))

    msg = wcfg["message"].replace("{mention}", member.mention)\
                         .replace("{name}", str(member))\
                         .replace("{server}", member.guild.name)\
                         .replace("{count}", str(member.guild.member_count))

    e.description = msg

    if wcfg.get("show_avatar", True):
        e.set_thumbnail(url=member.display_avatar.url)

    e.add_field(name="👤 Membre", value=member.mention, inline=True)
    e.add_field(name="🔢 Arrivée", value=f"#{member.guild.member_count}", inline=True)
    e.add_field(name="📅 Compte créé", value=f"Il y a {account_age_str}", inline=True)

    if join_count > 1:
        e.add_field(name="🔄 Fois rejoint", value=f"{join_count}e fois", inline=True)

    if inviter and wcfg.get("show_inviter", True):
        # Compter les invitations de l'inviteur
        inv_db = db_load("invites").get(str(member.guild.id), {})
        inv_count = inv_db.get(str(inviter.id), 0)
        invite_type = "lien d'invitation personnalisé du serveur"
        e.add_field(
            name="📩 Invité par",
            value=f"{inviter.mention} (via **{invite_type}**)",
            inline=False
        )

    e.set_footer(text=f"{member.guild.name} • Nous sommes désormais {member.guild.member_count} !")
    e.set_author(name=f"Bienvenue sur {member.guild.name} !", icon_url=member.guild.icon.url if member.guild.icon else None)

    await ch.send(content=member.mention, embed=e)

    # Attribuer le rôle de bienvenue
    if wcfg.get("role"):
        role = member.guild.get_role(int(wcfg["role"]))
        if role:
            try: await member.add_roles(role)
            except: pass

async def _do_goodbye(member: discord.Member):
    gcfg = cfg["goodbye"]
    if not gcfg["enabled"] or not gcfg["channel"]: return
    ch = member.guild.get_channel(int(gcfg["channel"]))
    if not ch: return
    msg = gcfg["message"].replace("{mention}", member.mention)\
                          .replace("{name}", str(member))\
                          .replace("{server}", member.guild.name)
    e = em(msg, color=cfg["warn_color"])
    e.set_thumbnail(url=member.display_avatar.url)
    e.set_footer(text=f"Nous sommes maintenant {member.guild.member_count} membres.")
    await ch.send(embed=e)

# ════════════════════════════════════════════════════════════════════
#  INVITES TRACKER
# ════════════════════════════════════════════════════════════════════
async def _track_invite(member: discord.Member):
    guild = member.guild
    try:
        new_invites = await guild.invites()
        old = invite_cache.get(guild.id, {})
        for inv in new_invites:
            if old.get(inv.code, 0) < inv.uses:
                inv_db = db_load("invites")
                gid, uid = str(guild.id), str(inv.inviter.id)
                inv_db.setdefault(gid, {})
                inv_db[gid].setdefault(uid, 0)
                inv_db[gid][uid] += 1
                db_save("invites", inv_db)
                rewards = db_get("invite_rewards", guild.id)
                count = inv_db[gid][uid]
                for threshold_str, role_id in rewards.items():
                    if count == int(threshold_str):
                        role = guild.get_role(int(role_id))
                        if role:
                            try: await inv.inviter.add_roles(role)
                            except: pass
                break
        invite_cache[guild.id] = {inv.code: inv.uses for inv in new_invites}
    except: pass

# ════════════════════════════════════════════════════════════════════
#  COMMANDES PERSONNALISÉES
# ════════════════════════════════════════════════════════════════════
async def _run_custom_cmd(message: discord.Message):
    prefix = cfg["prefix"]
    if not message.content.startswith(prefix): return
    cmd = message.content[len(prefix):].split()[0].lower()
    data = db_get("custom_commands", message.guild.id)
    if cmd in data:
        resp = data[cmd].replace("{user}", message.author.mention)\
                        .replace("{server}", message.guild.name)\
                        .replace("{members}", str(message.guild.member_count))
        await message.channel.send(resp)

# ════════════════════════════════════════════════════════════════════
#  TEMPVOC
# ════════════════════════════════════════════════════════════════════
TEMPVOC_OWNERS: dict[int, int] = {}  # channel_id → owner_id

async def _tempvoc_handler(member, before, after):
    data = db_get("tempvoc_config", member.guild.id)
    trigger_id = data.get("trigger_channel")
    if trigger_id and after.channel and after.channel.id == int(trigger_id):
        overwrites = {
            member: discord.PermissionOverwrite(manage_channels=True, connect=True, speak=True)
        }
        ch = await member.guild.create_voice_channel(
            f"🔊 {member.display_name}",
            category=after.channel.category,
            overwrites=overwrites
        )
        TEMPVOC_OWNERS[ch.id] = member.id
        await member.move_to(ch)
    if before.channel and before.channel.id in TEMPVOC_OWNERS:
        if len(before.channel.members) == 0:
            try:
                await before.channel.delete(reason="Tempvoc vide")
                del TEMPVOC_OWNERS[before.channel.id]
            except: pass

# ════════════════════════════════════════════════════════════════════
#  TASKS
# ════════════════════════════════════════════════════════════════════
@tasks.loop(minutes=10)
async def update_counters():
    counters_db = db_load("counters")
    for gid_str, channels in counters_db.items():
        guild = bot.get_guild(int(gid_str))
        if not guild: continue
        for cid_str, data in channels.items():
            ch = guild.get_channel(int(cid_str))
            if not ch: continue
            try: await ch.edit(name=f"📊 {data['name']}: {guild.member_count}")
            except: pass

@tasks.loop(seconds=30)
async def check_giveaways():
    gw_db = db_load("giveaways")
    now = time.time()
    changed = False
    for gid, giveaways in gw_db.items():
        for gw in giveaways:
            if gw.get("ended"): continue
            if now >= gw["end_time"]:
                guild = bot.get_guild(int(gid))
                if not guild: continue
                channel = guild.get_channel(gw["channel_id"])
                if not channel: continue
                try:
                    msg = await channel.fetch_message(gw["message_id"])
                except: continue
                reaction = discord.utils.get(msg.reactions, emoji="🎉")
                participants = []
                if reaction:
                    async for u in reaction.users():
                        if not u.bot:
                            participants.append(u)
                if participants:
                    winners = random.sample(participants, min(gw["winners"], len(participants)))
                    wm = ", ".join(w.mention for w in winners)
                    await channel.send(embed=em(
                        f"🎉 **Giveaway terminé !**\nPrix : **{gw['prize']}**\nGagnant(s) : {wm}",
                        color=cfg["success_color"]))
                else:
                    await channel.send(embed=em(
                        "Giveaway terminé mais personne n'a participé 😢",
                        color=cfg["warn_color"]))
                gw["ended"] = True
                changed = True
    if changed:
        db_save("giveaways", gw_db)

# ════════════════════════════════════════════════════════════════════
# ██████████████████████████ COMMANDES ███████████████████████████████
# ════════════════════════════════════════════════════════════════════

# ────────────────────────────────────────────────────────────────────
#  WHITELIST / BLACKLIST
# ────────────────────────────────────────────────────────────────────

@bot.group(name="wl", invoke_without_command=True)
@is_admin()
async def cmd_wl(ctx):
    """Gestion de la whitelist — +wl add/remove/list/clear"""
    wl = cfg.get("whitelist", [])
    if not wl:
        return await ctx.send(embed=em("La whitelist est vide.", color=cfg["color"]))
    lines = []
    for uid in wl:
        m = ctx.guild.get_member(int(uid))
        lines.append(f"• {m.mention if m else f'<@{uid}>'} (`{uid}`)")
    e = em("\n".join(lines), title="✅ Whitelist", color=cfg["success_color"])
    e.set_footer(text=f"{len(wl)} utilisateur(s) whitelisté(s)")
    await ctx.send(embed=e)

@cmd_wl.command(name="add")
@is_admin()
async def wl_add(ctx, member: discord.Member):
    """Ajouter un utilisateur à la whitelist"""
    wl = cfg.setdefault("whitelist", [])
    if str(member.id) in [str(x) for x in wl]:
        return await ctx.send(embed=warn(f"**{member}** est déjà whitelisté."))
    wl.append(member.id)
    save_config(cfg)
    await ctx.send(embed=ok(f"**{member}** ajouté à la whitelist."))
    await send_log(ctx.guild, em(f"✅ **WL+** | {member.mention} par {ctx.author.mention}", color=cfg["success_color"]))

@cmd_wl.command(name="remove")
@is_admin()
async def wl_remove(ctx, member: discord.Member):
    """Retirer un utilisateur de la whitelist"""
    wl = cfg.get("whitelist", [])
    new_wl = [x for x in wl if str(x) != str(member.id)]
    if len(new_wl) == len(wl):
        return await ctx.send(embed=err(f"**{member}** n'est pas dans la whitelist."))
    cfg["whitelist"] = new_wl
    save_config(cfg)
    await ctx.send(embed=ok(f"**{member}** retiré de la whitelist."))

@cmd_wl.command(name="clear")
@is_admin()
async def wl_clear(ctx):
    """Vider la whitelist"""
    cfg["whitelist"] = []
    save_config(cfg)
    await ctx.send(embed=ok("Whitelist vidée."))

@bot.group(name="bl", invoke_without_command=True)
@is_admin()
async def cmd_bl(ctx):
    """Gestion de la blacklist — +bl add/remove/list/clear"""
    bl = cfg.get("blacklist", [])
    if not bl:
        return await ctx.send(embed=em("La blacklist est vide.", color=cfg["color"]))
    lines = []
    for uid in bl:
        m = ctx.guild.get_member(int(uid))
        lines.append(f"• {m.mention if m else f'<@{uid}>'} (`{uid}`)")
    e = em("\n".join(lines), title="🚫 Blacklist", color=cfg["error_color"])
    e.set_footer(text=f"{len(bl)} utilisateur(s) blacklisté(s)")
    await ctx.send(embed=e)

@cmd_bl.command(name="add")
@is_admin()
async def bl_add(ctx, member: discord.Member, *, reason: str = "Aucune raison"):
    """Blacklister un utilisateur"""
    bl = cfg.setdefault("blacklist", [])
    if str(member.id) in [str(x) for x in bl]:
        return await ctx.send(embed=warn(f"**{member}** est déjà blacklisté."))
    bl.append(member.id)
    save_config(cfg)
    await ctx.send(embed=ok(f"**{member}** blacklisté.\nRaison : {reason}"))
    await send_log(ctx.guild, em(f"🚫 **BL+** | {member.mention} par {ctx.author.mention}\nRaison : {reason}", color=cfg["error_color"]))
    try:
        await member.send(embed=em(
            f"Tu as été blacklisté sur **{ctx.guild.name}** et ne peux plus utiliser le bot.\nRaison : {reason}",
            color=cfg["error_color"]))
    except: pass

@cmd_bl.command(name="remove")
@is_admin()
async def bl_remove(ctx, member: discord.Member):
    """Retirer un utilisateur de la blacklist"""
    bl = cfg.get("blacklist", [])
    new_bl = [x for x in bl if str(x) != str(member.id)]
    if len(new_bl) == len(bl):
        return await ctx.send(embed=err(f"**{member}** n'est pas dans la blacklist."))
    cfg["blacklist"] = new_bl
    save_config(cfg)
    await ctx.send(embed=ok(f"**{member}** retiré de la blacklist."))

@cmd_bl.command(name="clear")
@is_admin()
async def bl_clear(ctx):
    """Vider la blacklist"""
    cfg["blacklist"] = []
    save_config(cfg)
    await ctx.send(embed=ok("Blacklist vidée."))

# ────────────────────────────────────────────────────────────────────
#  PERMISSIONS PAR RÔLE
# ────────────────────────────────────────────────────────────────────

@bot.group(name="roleperm", aliases=["rp"], invoke_without_command=True)
@is_admin()
async def cmd_roleperm(ctx):
    """Gérer les permissions de commandes par rôle — +roleperm add/remove/list/reset"""
    role_perms = cfg.get("role_permissions", {})
    if not role_perms:
        return await ctx.send(embed=em(
            "Aucune permission par rôle configurée.\n"
            f"Utilise `{cfg['prefix']}roleperm add @rôle <commande>` pour en ajouter.",
            color=cfg["color"]))
    lines = []
    for rid, cmds in role_perms.items():
        role = ctx.guild.get_role(int(rid))
        name = role.mention if role else f"`{rid}`"
        lines.append(f"• {name} → `{'`, `'.join(cmds)}`")
    e = em("\n".join(lines), title="🔐 Permissions par rôle", color=cfg["color"])
    await ctx.send(embed=e)

@cmd_roleperm.command(name="add")
@is_admin()
async def roleperm_add(ctx, role: discord.Role, *, commands_str: str):
    """Donner accès à des commandes à un rôle
    
    Exemples:
      +roleperm add @Modérateur warn kick ban
      +roleperm add @Staff * (accès à tout)
    """
    role_perms = cfg.setdefault("role_permissions", {})
    cmds = commands_str.split()
    rid = str(role.id)
    role_perms.setdefault(rid, [])
    added = []
    for cmd in cmds:
        if cmd not in role_perms[rid]:
            role_perms[rid].append(cmd)
            added.append(cmd)
    save_config(cfg)
    if added:
        await ctx.send(embed=ok(f"Rôle **{role.name}** → accès ajouté : `{'`, `'.join(added)}`"))
    else:
        await ctx.send(embed=warn("Toutes ces commandes sont déjà attribuées à ce rôle."))

@cmd_roleperm.command(name="remove")
@is_admin()
async def roleperm_remove(ctx, role: discord.Role, *, commands_str: str):
    """Retirer l'accès à des commandes d'un rôle"""
    role_perms = cfg.get("role_permissions", {})
    rid = str(role.id)
    if rid not in role_perms:
        return await ctx.send(embed=err(f"Aucune permission configurée pour **{role.name}**."))
    cmds = commands_str.split()
    for cmd in cmds:
        if cmd in role_perms[rid]:
            role_perms[rid].remove(cmd)
    if not role_perms[rid]:
        del role_perms[rid]
    save_config(cfg)
    await ctx.send(embed=ok(f"Permissions retirées pour **{role.name}** : `{'`, `'.join(cmds)}`"))

@cmd_roleperm.command(name="reset")
@is_admin()
async def roleperm_reset(ctx, role: discord.Role = None):
    """Réinitialiser les permissions d'un rôle (ou tous)"""
    role_perms = cfg.get("role_permissions", {})
    if role:
        rid = str(role.id)
        if rid in role_perms:
            del role_perms[rid]
        save_config(cfg)
        await ctx.send(embed=ok(f"Permissions réinitialisées pour **{role.name}**."))
    else:
        cfg["role_permissions"] = {}
        save_config(cfg)
        await ctx.send(embed=ok("Toutes les permissions par rôle réinitialisées."))

@cmd_roleperm.command(name="check")
@is_admin()
async def roleperm_check(ctx, member: discord.Member, command_name: str):
    """Vérifier si un membre peut utiliser une commande"""
    if is_blacklisted(member.id):
        return await ctx.send(embed=em(f"❌ **{member}** est blacklisté.", color=cfg["error_color"]))
    if is_whitelisted(member.id):
        return await ctx.send(embed=em(f"✅ **{member}** est whitelisté — accès total.", color=cfg["success_color"]))
    if member.guild_permissions.administrator:
        return await ctx.send(embed=em(f"✅ **{member}** est administrateur — accès total.", color=cfg["success_color"]))
    has_access = has_role_permission(member, command_name)
    color = cfg["success_color"] if has_access else cfg["error_color"]
    icon = "✅" if has_access else "❌"
    await ctx.send(embed=em(
        f"{icon} **{member}** {'peut' if has_access else 'ne peut pas'} utiliser `{command_name}`.",
        color=color))

# ────────────────────────────────────────────────────────────────────
#  MODÉRATION
# ────────────────────────────────────────────────────────────────────

@bot.command(name="warn")
@is_mod()
async def cmd_warn(ctx, member: discord.Member, *, reason="Aucune raison"):
    """Avertir un membre"""
    warns = db_get("warns", ctx.guild.id)
    uid = str(member.id)
    warns.setdefault(uid, [])
    warns[uid].append({"reason": reason, "by": str(ctx.author), "at": str(datetime.utcnow())})
    db_set("warns", ctx.guild.id, warns)
    count = len(warns[uid])
    await ctx.send(embed=ok(f"**{member}** averti ({count} warn(s)).\nRaison : {reason}"))
    await send_log(ctx.guild,
        em(f"⚠️ **Warn** | {member.mention} par {ctx.author.mention}\nRaison : {reason}",
           color=cfg["warn_color"]))
    try:
        await member.send(embed=em(
            f"Tu as reçu un avertissement sur **{ctx.guild.name}**.\nRaison : {reason}",
            color=cfg["warn_color"]))
    except: pass

@bot.command(name="warns")
@is_mod()
async def cmd_warns(ctx, member: discord.Member):
    """Voir les warns d'un membre"""
    warns_list = db_get("warns", ctx.guild.id).get(str(member.id), [])
    if not warns_list:
        return await ctx.send(embed=ok(f"**{member}** n'a aucun avertissement."))
    desc = "\n".join(f"**{i+1}.** {w['reason']} — par {w['by']}" for i, w in enumerate(warns_list))
    await ctx.send(embed=em(desc, title=f"⚠️ Warns de {member}", color=cfg["warn_color"]))

@bot.command(name="clearwarns")
@is_admin()
async def cmd_clearwarns(ctx, member: discord.Member):
    """Effacer tous les warns d'un membre"""
    warns = db_get("warns", ctx.guild.id)
    warns[str(member.id)] = []
    db_set("warns", ctx.guild.id, warns)
    await ctx.send(embed=ok(f"Avertissements de **{member}** effacés."))

@bot.command(name="kick")
@commands.has_permissions(kick_members=True)
async def cmd_kick(ctx, member: discord.Member, *, reason="Aucune raison"):
    """Expulser un membre"""
    try:
        await member.send(embed=em(
            f"Tu as été expulsé de **{ctx.guild.name}**.\nRaison : {reason}",
            color=cfg["error_color"]))
    except: pass
    await member.kick(reason=reason)
    await ctx.send(embed=ok(f"**{member}** a été expulsé.\nRaison : {reason}"))
    await send_log(ctx.guild,
        em(f"👢 **Kick** | {member.mention} par {ctx.author.mention}\nRaison : {reason}",
           color=cfg["error_color"]))

@bot.command(name="ban")
@commands.has_permissions(ban_members=True)
async def cmd_ban(ctx, member: discord.Member, *, reason="Aucune raison"):
    """Bannir un membre"""
    try:
        await member.send(embed=em(
            f"Tu as été banni de **{ctx.guild.name}**.\nRaison : {reason}",
            color=cfg["error_color"]))
    except: pass
    await member.ban(reason=reason)
    await ctx.send(embed=ok(f"**{member}** a été banni.\nRaison : {reason}"))
    await send_log(ctx.guild,
        em(f"🔨 **Ban** | {member.mention} par {ctx.author.mention}\nRaison : {reason}",
           color=cfg["error_color"]))

@bot.command(name="softban")
@commands.has_permissions(ban_members=True)
async def cmd_softban(ctx, member: discord.Member, *, reason="Aucune raison"):
    """Softban (ban + unban pour supprimer les messages)"""
    await member.ban(reason=f"Softban: {reason}", delete_message_days=7)
    await ctx.guild.unban(member, reason="Softban")
    await ctx.send(embed=ok(f"**{member}** softban (messages supprimés)."))

@bot.command(name="tempban")
@commands.has_permissions(ban_members=True)
async def cmd_tempban(ctx, member: discord.Member, duration: str, *, reason="Aucune raison"):
    """Bannir temporairement (ex: 10m, 2h, 1d)"""
    secs = parse_duration(duration)
    if not secs:
        return await ctx.send(embed=err("Durée invalide. Ex : `10m`, `2h`, `1d`"))
    await member.ban(reason=reason)
    await ctx.send(embed=ok(f"**{member}** banni pour **{duration}**.\nRaison : {reason}"))
    await asyncio.sleep(secs)
    try: await ctx.guild.unban(member, reason="Tempban expiré")
    except: pass

@bot.command(name="unban")
@commands.has_permissions(ban_members=True)
async def cmd_unban(ctx, *, user_tag: str):
    """Débannir (nom#discrim ou ID)"""
    bans = [e async for e in ctx.guild.bans()]
    for entry in bans:
        if str(entry.user) == user_tag or str(entry.user.id) == user_tag:
            await ctx.guild.unban(entry.user)
            return await ctx.send(embed=ok(f"**{entry.user}** a été débanni."))
    await ctx.send(embed=err(f"Aucun ban trouvé pour `{user_tag}`."))

@bot.command(name="banlist")
@commands.has_permissions(ban_members=True)
async def cmd_banlist(ctx):
    """Liste des membres bannis"""
    bans = [e async for e in ctx.guild.bans()]
    if not bans:
        return await ctx.send(embed=ok("Aucun membre banni."))
    desc = "\n".join(f"• {b.user} (`{b.user.id}`)" for b in bans[:20])
    if len(bans) > 20: desc += f"\n… et {len(bans)-20} autres"
    await ctx.send(embed=em(desc, title=f"🔨 Bans ({len(bans)})", color=cfg["error_color"]))

@bot.command(name="mute")
@is_mod()
async def cmd_mute(ctx, member: discord.Member, *, reason="Aucune raison"):
    """Mute permanent (28j Discord max)"""
    await member.timeout(timedelta(days=28), reason=reason)
    await ctx.send(embed=ok(f"**{member}** mis en sourdine."))
    await send_log(ctx.guild,
        em(f"🔇 **Mute** | {member.mention} par {ctx.author.mention}\nRaison : {reason}",
           color=cfg["warn_color"]))

@bot.command(name="tempmute")
@is_mod()
async def cmd_tempmute(ctx, member: discord.Member, duration: str, *, reason="Aucune raison"):
    """Mute temporaire (ex: 10m, 2h)"""
    secs = parse_duration(duration)
    if not secs:
        return await ctx.send(embed=err("Durée invalide. Ex : `10m`, `2h`"))
    await member.timeout(timedelta(seconds=secs), reason=reason)
    await ctx.send(embed=ok(f"**{member}** muté pour **{duration}**."))

@bot.command(name="unmute")
@is_mod()
async def cmd_unmute(ctx, member: discord.Member):
    """Lever la sourdine d'un membre"""
    await member.timeout(None)
    await ctx.send(embed=ok(f"**{member}** démute."))

@bot.command(name="unmuteall")
@is_admin()
async def cmd_unmuteall(ctx):
    """Lever la sourdine de tous les membres"""
    count = 0
    for m in ctx.guild.members:
        if m.is_timed_out():
            try: await m.timeout(None); count += 1
            except: pass
    await ctx.send(embed=ok(f"{count} membre(s) démuté(s)."))

@bot.command(name="mutelist")
@is_mod()
async def cmd_mutelist(ctx):
    """Liste des membres mutés"""
    muted = [m for m in ctx.guild.members if m.is_timed_out()]
    if not muted:
        return await ctx.send(embed=ok("Aucun membre muté."))
    desc = "\n".join(f"• {m.mention}" for m in muted[:20])
    await ctx.send(embed=em(desc, title=f"🔇 Mutés ({len(muted)})", color=cfg["warn_color"]))

@bot.command(name="clear", aliases=["purge"])
@is_mod()
async def cmd_clear(ctx, amount: int = 10, member: discord.Member = None):
    """Supprimer des messages (max 500)"""
    if not 1 <= amount <= 500:
        return await ctx.send(embed=err("Entre 1 et 500."))
    await ctx.message.delete()
    check = (lambda m: m.author == member) if member else None
    deleted = await ctx.channel.purge(limit=amount, check=check)
    await ctx.send(embed=ok(f"{len(deleted)} message(s) supprimé(s)."), delete_after=4)

@bot.command(name="nick")
@is_mod()
async def cmd_nick(ctx, member: discord.Member, *, nick: str = None):
    """Changer le surnom d'un membre"""
    await member.edit(nick=nick)
    msg = f"Surnom de **{member}** mis à `{nick}`." if nick else f"Surnom de **{member}** réinitialisé."
    await ctx.send(embed=ok(msg))

@bot.command(name="derank")
@is_admin()
async def cmd_derank(ctx, member: discord.Member, *, reason="Aucune raison"):
    """Retirer tous les rôles d'un membre"""
    roles = [r for r in member.roles if r != ctx.guild.default_role and r.is_assignable()]
    await member.remove_roles(*roles, reason=reason)
    await ctx.send(embed=ok(f"Tous les rôles de **{member}** retirés."))

@bot.command(name="addrole")
@is_mod()
async def cmd_addrole(ctx, member: discord.Member, role: discord.Role):
    """Ajouter un rôle à un membre"""
    await member.add_roles(role)
    await ctx.send(embed=ok(f"Rôle **{role.name}** ajouté à {member.mention}."))

@bot.command(name="delrole")
@is_mod()
async def cmd_delrole(ctx, member: discord.Member, role: discord.Role):
    """Retirer un rôle à un membre"""
    await member.remove_roles(role)
    await ctx.send(embed=ok(f"Rôle **{role.name}** retiré de {member.mention}."))

@bot.command(name="lock")
@is_mod()
async def cmd_lock(ctx, channel: discord.TextChannel = None):
    """Verrouiller un salon"""
    ch = channel or ctx.channel
    await ch.set_permissions(ctx.guild.default_role, send_messages=False)
    await ctx.send(embed=ok(f"🔒 {ch.mention} verrouillé."))

@bot.command(name="unlock")
@is_mod()
async def cmd_unlock(ctx, channel: discord.TextChannel = None):
    """Déverrouiller un salon"""
    ch = channel or ctx.channel
    await ch.set_permissions(ctx.guild.default_role, send_messages=None)
    await ctx.send(embed=ok(f"🔓 {ch.mention} déverrouillé."))

@bot.command(name="hide")
@is_mod()
async def cmd_hide(ctx, channel: discord.TextChannel = None):
    """Masquer un salon"""
    ch = channel or ctx.channel
    await ch.set_permissions(ctx.guild.default_role, view_channel=False)
    await ctx.send(embed=ok(f"👁️ {ch.mention} masqué."))

@bot.command(name="unhide")
@is_mod()
async def cmd_unhide(ctx, channel: discord.TextChannel = None):
    """Révéler un salon"""
    ch = channel or ctx.channel
    await ch.set_permissions(ctx.guild.default_role, view_channel=None)
    await ctx.send(embed=ok(f"👁️ {ch.mention} révélé."))

@bot.command(name="lockdown")
@is_admin()
async def cmd_lockdown(ctx):
    """Activer/désactiver le lockdown anti-raid"""
    gid = ctx.guild.id
    if gid in bot.lockdown_guilds:
        bot.lockdown_guilds.discard(gid)
        await ctx.send(embed=ok("🔓 Lockdown levé."))
    else:
        bot.lockdown_guilds.add(gid)
        await ctx.send(embed=warn("🔒 Lockdown activé — nouveaux membres bloqués."))

@bot.command(name="note")
@is_mod()
async def cmd_note(ctx, member: discord.Member, *, note: str):
    """Ajouter une note sur un membre"""
    notes = db_get("notes", ctx.guild.id)
    uid = str(member.id)
    notes.setdefault(uid, [])
    notes[uid].append({"note": note, "by": str(ctx.author), "at": str(datetime.utcnow())})
    db_set("notes", ctx.guild.id, notes)
    await ctx.send(embed=ok(f"Note ajoutée pour **{member}**."))

@bot.command(name="notes")
@is_mod()
async def cmd_notes(ctx, member: discord.Member):
    """Voir les notes d'un membre"""
    notes_list = db_get("notes", ctx.guild.id).get(str(member.id), [])
    if not notes_list:
        return await ctx.send(embed=ok(f"Aucune note pour **{member}**."))
    desc = "\n".join(f"**{i+1}.** {n['note']} — {n['by']}" for i, n in enumerate(notes_list))
    await ctx.send(embed=em(desc, title=f"📌 Notes de {member}", color=cfg["color"]))

@bot.command(name="userinfo", aliases=["ui", "whois"])
@is_mod()
async def cmd_userinfo(ctx, member: discord.Member = None):
    """Infos détaillées sur un membre"""
    m = member or ctx.author
    roles = [r.mention for r in m.roles[1:]][:10]
    e = em(color=cfg["color"])
    e.set_author(name=str(m), icon_url=m.display_avatar.url)
    e.set_thumbnail(url=m.display_avatar.url)
    e.add_field(name="ID",          value=str(m.id))
    e.add_field(name="Compte créé", value=discord.utils.format_dt(m.created_at, "R"))
    e.add_field(name="A rejoint",   value=discord.utils.format_dt(m.joined_at,  "R"))
    e.add_field(name=f"Rôles ({len(m.roles)-1})",
                value=" ".join(roles) or "Aucun", inline=False)
    warns_count = len(db_get("warns", ctx.guild.id).get(str(m.id), []))
    wl_status = "✅ WL" if is_whitelisted(m.id) else ("🚫 BL" if is_blacklisted(m.id) else "—")
    e.add_field(name="⚠️ Warns", value=str(warns_count))
    e.add_field(name="🔐 Statut", value=wl_status)
    await ctx.send(embed=e)

@bot.command(name="serverinfo", aliases=["si"])
async def cmd_serverinfo(ctx):
    """Infos sur le serveur"""
    g = ctx.guild
    e = em(color=cfg["color"])
    e.set_author(name=g.name, icon_url=g.icon.url if g.icon else None)
    e.add_field(name="Membres",  value=str(g.member_count))
    e.add_field(name="Salons",   value=str(len(g.channels)))
    e.add_field(name="Rôles",    value=str(len(g.roles)))
    e.add_field(name="Boosts",   value=str(g.premium_subscription_count))
    e.add_field(name="Créé le",  value=discord.utils.format_dt(g.created_at, "D"))
    e.add_field(name="Owner",    value=g.owner.mention if g.owner else "?")
    await ctx.send(embed=e)

@bot.command(name="avatar", aliases=["av"])
async def cmd_avatar(ctx, member: discord.Member = None):
    """Afficher l'avatar d'un membre"""
    m = member or ctx.author
    e = em(title=f"Avatar de {m}", color=cfg["color"])
    e.set_image(url=m.display_avatar.url)
    await ctx.send(embed=e)

@bot.command(name="banner")
async def cmd_banner(ctx, member: discord.Member = None):
    """Afficher la bannière d'un membre"""
    m = member or ctx.author
    user = await bot.fetch_user(m.id)
    if not user.banner:
        return await ctx.send(embed=err(f"**{m}** n'a pas de bannière."))
    e = em(title=f"Bannière de {m}", color=cfg["color"])
    e.set_image(url=user.banner.url)
    await ctx.send(embed=e)

@bot.command(name="roleinfo")
async def cmd_roleinfo(ctx, role: discord.Role):
    """Infos sur un rôle"""
    e = em(color=role.color.value or cfg["color"])
    e.set_author(name=f"@{role.name}")
    e.add_field(name="ID",       value=str(role.id))
    e.add_field(name="Membres",  value=str(len(role.members)))
    e.add_field(name="Couleur",  value=str(role.color))
    e.add_field(name="Mentionnable", value="Oui" if role.mentionable else "Non")
    e.add_field(name="Hoisted",  value="Oui" if role.hoist else "Non")
    e.add_field(name="Créé le",  value=discord.utils.format_dt(role.created_at, "D"))
    await ctx.send(embed=e)

@bot.command(name="members")
async def cmd_members(ctx, role: discord.Role = None):
    """Liste des membres d'un rôle"""
    if role is None:
        return await ctx.send(embed=em(f"**{ctx.guild.name}** — {ctx.guild.member_count} membres.", color=cfg["color"]))
    if not role.members:
        return await ctx.send(embed=err(f"Aucun membre avec le rôle **{role.name}**."))
    lines = [m.mention for m in role.members[:30]]
    extra = len(role.members) - 30
    desc = " ".join(lines) + (f"\n… et {extra} autres" if extra > 0 else "")
    await ctx.send(embed=em(desc, title=f"👥 {role.name} ({len(role.members)})", color=cfg["color"]))

# ────────────────────────────────────────────────────────────────────
#  CONFIG ANTI-RAID / ANTISPAM / AUTOMOD
# ────────────────────────────────────────────────────────────────────

@bot.command(name="antiraid")
@is_admin()
async def cmd_antiraid(ctx, action: str = "status", value: str = None):
    """!antiraid <enable|disable|action|rate|status>"""
    ar = cfg["antiraid"]
    action = action.lower()
    if action == "enable":    ar["enabled"] = True; save_config(cfg)
    elif action == "disable": ar["enabled"] = False; save_config(cfg)
    elif action == "action" and value in ("kick", "ban", "timeout"):
        ar["action"] = value; save_config(cfg)
    elif action == "rate" and value:
        try: ar["join_rate"] = int(value); save_config(cfg)
        except: return await ctx.send(embed=err("Nombre invalide."))
    status = "✅ Activé" if ar["enabled"] else "❌ Désactivé"
    await ctx.send(embed=em(
        f"**Anti-Raid** : {status}\nAction : `{ar['action']}` | Rate : `{ar['join_rate']}` joins/{ar['join_interval']}s",
        color=cfg["color"]))

@bot.command(name="antispam")
@is_admin()
async def cmd_antispam(ctx, action: str = "status", value: str = None):
    """!antispam <enable|disable|action|limit|status>"""
    asp = cfg["antispam"]
    action = action.lower()
    if action == "enable":    asp["enabled"] = True; save_config(cfg)
    elif action == "disable": asp["enabled"] = False; save_config(cfg)
    elif action == "action" and value in ("mute", "kick", "ban"):
        asp["action"] = value; save_config(cfg)
    elif action == "limit" and value:
        try: asp["msg_limit"] = int(value); save_config(cfg)
        except: return await ctx.send(embed=err("Nombre invalide."))
    status = "✅ Activé" if asp["enabled"] else "❌ Désactivé"
    await ctx.send(embed=em(
        f"**Antispam** : {status}\nAction : `{asp['action']}` | Limite : `{asp['msg_limit']}` msgs/{asp['interval']}s",
        color=cfg["color"]))

@bot.command(name="automod")
@is_admin()
async def cmd_automod(ctx, action: str, *, word: str = None):
    """!automod <enable|disable|add|remove|list>"""
    data = db_get("automod", ctx.guild.id)
    data.setdefault("enabled", False)
    data.setdefault("words", [])
    action = action.lower()
    if action == "enable":  data["enabled"] = True
    elif action == "disable": data["enabled"] = False
    elif action == "add" and word:
        if word.lower() not in data["words"]:
            data["words"].append(word.lower())
        await ctx.send(embed=ok(f"Mot `{word}` ajouté au filtre."))
    elif action == "remove" and word:
        data["words"] = [w for w in data["words"] if w != word.lower()]
        await ctx.send(embed=ok(f"Mot `{word}` retiré du filtre."))
    elif action == "list":
        desc = ", ".join(f"`{w}`" for w in data["words"]) or "Aucun mot filtré."
        return await ctx.send(embed=em(desc, title="🚫 Mots filtrés", color=cfg["color"]))
    db_set("automod", ctx.guild.id, data)
    if action in ("enable", "disable"):
        status = "✅ Activé" if data["enabled"] else "❌ Désactivé"
        await ctx.send(embed=ok(f"AutoMod : {status}"))

@bot.command(name="invitefilter")
@is_admin()
async def cmd_invitefilter(ctx, state: str):
    """Filtrer les liens Discord (enable/disable)"""
    data = db_get("invite_filter", ctx.guild.id)
    if state.lower() == "enable":
        data["enabled"] = True
        db_set("invite_filter", ctx.guild.id, data)
        await ctx.send(embed=ok("Filtre d'invitations activé."))
    elif state.lower() == "disable":
        data["enabled"] = False
        db_set("invite_filter", ctx.guild.id, data)
        await ctx.send(embed=ok("Filtre d'invitations désactivé."))
    else:
        await ctx.send(embed=err("Utilise `enable` ou `disable`."))

# ────────────────────────────────────────────────────────────────────
#  TICKETS MODULABLES (Pro)
# ────────────────────────────────────────────────────────────────────
# Structure : config par serveur
# tickets_config: { category, mod_role, log_channel, panels: [{id, label, emoji, description}] }

class TicketSelectMenu(discord.ui.Select):
    """Menu déroulant pour choisir le type de ticket"""
    def __init__(self, panels: list):
        options = []
        for p in panels[:25]:
            options.append(discord.SelectOption(
                label=p.get("label", "Support"),
                value=str(p.get("id", 0)),
                emoji=p.get("emoji", "🎫"),
                description=p.get("description", "")[:100]
            ))
        super().__init__(placeholder="📋 Choisir le type de ticket…", options=options)

    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        panel_id = self.values[0]
        data = db_get("tickets_config", guild.id)

        # Vérifier si l'utilisateur a déjà un ticket
        existing = discord.utils.get(guild.text_channels,
                                     name=f"ticket-{interaction.user.name.lower()}")
        if existing:
            return await interaction.response.send_message(
                embed=warn(f"Tu as déjà un ticket ouvert : {existing.mention}"), ephemeral=True)

        panels = data.get("panels", [])
        panel = next((p for p in panels if str(p.get("id")) == panel_id), None)
        panel_label = panel.get("label", "Support") if panel else "Support"

        category_id = data.get("category")
        category = guild.get_channel(int(category_id)) if category_id else None

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user:   discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True),
        }
        mod_role_id = data.get("mod_role")
        if mod_role_id:
            mod_role = guild.get_role(int(mod_role_id))
            if mod_role:
                overwrites[mod_role] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, manage_channels=True)

        ch = await guild.create_text_channel(
            f"ticket-{interaction.user.name}",
            category=category, overwrites=overwrites,
            topic=f"Ticket {panel_label} | {interaction.user} ({interaction.user.id})")

        view = TicketManageView()
        e = discord.Embed(
            title=f"🎫 Ticket — {panel_label}",
            description=f"Bienvenue {interaction.user.mention} !\n\n"
                        f"Merci d'avoir ouvert un ticket **{panel_label}**.\n"
                        f"Explique ton problème en détail, l'équipe va t'aider.",
            color=cfg["color"],
            timestamp=datetime.now(timezone.utc)
        )
        e.set_footer(text=f"{guild.name} • Support")
        e.set_thumbnail(url=interaction.user.display_avatar.url)
        await ch.send(content=interaction.user.mention, embed=e, view=view)
        await interaction.response.send_message(
            embed=ok(f"Ticket créé : {ch.mention}"), ephemeral=True)

        # Log
        log_cid = data.get("log_channel")
        if log_cid:
            log_ch = guild.get_channel(int(log_cid))
            if log_ch:
                le = em(f"🎫 Ticket **{panel_label}** ouvert par {interaction.user.mention} → {ch.mention}",
                        color=cfg["success_color"])
                try: await log_ch.send(embed=le)
                except: pass

class TicketPanelView(discord.ui.View):
    def __init__(self, panels: list):
        super().__init__(timeout=None)
        if len(panels) == 1:
            # Bouton simple si un seul type
            self.add_item(TicketSingleButton(panels[0]))
        else:
            self.add_item(TicketSelectMenu(panels))

class TicketSingleButton(discord.ui.Button):
    def __init__(self, panel: dict):
        super().__init__(
            label=panel.get("label", "Ouvrir un ticket"),
            emoji=panel.get("emoji", "🎫"),
            style=discord.ButtonStyle.primary,
            custom_id=f"ticket_open_{panel.get('id', 0)}"
        )
        self.panel = panel

    async def callback(self, interaction: discord.Interaction):
        await TicketSelectMenu([self.panel]).callback(interaction)

class TicketManageView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)

    @discord.ui.button(label="🔒 Fermer", style=discord.ButtonStyle.danger, custom_id="ticket_close_v2")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = db_get("tickets_config", interaction.guild.id)
        mod_role_id = data.get("mod_role")
        has_perm = interaction.user.guild_permissions.manage_channels
        if mod_role_id:
            mod_role = interaction.guild.get_role(int(mod_role_id))
            if mod_role and mod_role in interaction.user.roles:
                has_perm = True
        # Permettre aussi à l'owner du ticket de fermer
        if interaction.channel.topic and str(interaction.user.id) in interaction.channel.topic:
            has_perm = True
        if not has_perm:
            return await interaction.response.send_message(
                embed=err("Tu n'as pas la permission de fermer ce ticket."), ephemeral=True)
        await interaction.response.send_message(embed=warn("Ticket fermé dans 5 secondes..."))
        await asyncio.sleep(5)
        # Log avant suppression
        log_cid = data.get("log_channel")
        if log_cid:
            log_ch = interaction.guild.get_channel(int(log_cid))
            if log_ch:
                le = em(f"🔒 Ticket **{interaction.channel.name}** fermé par {interaction.user.mention}",
                        color=cfg["warn_color"])
                try: await log_ch.send(embed=le)
                except: pass
        await interaction.channel.delete(reason=f"Ticket fermé par {interaction.user}")

    @discord.ui.button(label="📋 Claim", style=discord.ButtonStyle.secondary, custom_id="ticket_claim")
    async def claim_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = db_get("tickets_config", interaction.guild.id)
        mod_role_id = data.get("mod_role")
        has_perm = interaction.user.guild_permissions.manage_channels
        if mod_role_id:
            mod_role = interaction.guild.get_role(int(mod_role_id))
            if mod_role and mod_role in interaction.user.roles:
                has_perm = True
        if not has_perm:
            return await interaction.response.send_message(
                embed=err("Seuls les modérateurs peuvent claim un ticket."), ephemeral=True)
        await interaction.response.send_message(
            embed=ok(f"Ticket pris en charge par {interaction.user.mention} 👋"))

@bot.group(name="ticket", aliases=["t"], invoke_without_command=True)
@is_admin()
async def cmd_ticket(ctx):
    """Gestion des tickets — +ticket panel | addtype | removetype | setcategory | setrole | setlog | types | close"""
    await ctx.send(embed=em(
        f"`{cfg['prefix']}ticket panel` — Envoyer le panneau\n"
        f"`{cfg['prefix']}ticket addtype <label> <emoji> [description]` — Ajouter un type\n"
        f"`{cfg['prefix']}ticket removetype <label>` — Supprimer un type\n"
        f"`{cfg['prefix']}ticket types` — Voir les types\n"
        f"`{cfg['prefix']}ticket setcategory <id>` — Catégorie pour les tickets\n"
        f"`{cfg['prefix']}ticket setrole <id>` — Rôle modération\n"
        f"`{cfg['prefix']}ticket setlog <#salon>` — Salon de logs tickets\n"
        f"`{cfg['prefix']}ticket close` — Fermer le ticket actuel",
        title="🎫 Système de Tickets", color=cfg["color"]))

@cmd_ticket.command(name="panel")
@is_admin()
async def ticket_panel(ctx, *, title: str = "Support"):
    """Envoyer le panneau d'ouverture de tickets"""
    data = db_get("tickets_config", ctx.guild.id)
    panels = data.get("panels", [])
    if not panels:
        # Créer un panel par défaut
        panels = [{"id": 1, "label": "Support", "emoji": "🎫", "description": "Ouvrir un ticket de support"}]
        data["panels"] = panels
        db_set("tickets_config", ctx.guild.id, data)
    view = TicketPanelView(panels)
    e = discord.Embed(
        title=f"🎫 {title}",
        description="Clique ci-dessous pour ouvrir un ticket.\nNotre équipe te répondra dès que possible.",
        color=cfg["color"]
    )
    e.set_footer(text=ctx.guild.name)
    await ctx.send(embed=e, view=view)
    try: await ctx.message.delete()
    except: pass

@cmd_ticket.command(name="addtype")
@is_admin()
async def ticket_addtype(ctx, label: str, emoji: str = "🎫", *, description: str = ""):
    """Ajouter un type de ticket au panel"""
    data = db_get("tickets_config", ctx.guild.id)
    panels = data.setdefault("panels", [])
    # Vérifier si le label existe déjà
    if any(p["label"].lower() == label.lower() for p in panels):
        return await ctx.send(embed=err(f"Un type `{label}` existe déjà."))
    new_id = max((p.get("id", 0) for p in panels), default=0) + 1
    panels.append({"id": new_id, "label": label, "emoji": emoji, "description": description})
    db_set("tickets_config", ctx.guild.id, data)
    await ctx.send(embed=ok(f"Type de ticket `{emoji} {label}` ajouté."))

@cmd_ticket.command(name="removetype")
@is_admin()
async def ticket_removetype(ctx, *, label: str):
    """Supprimer un type de ticket"""
    data = db_get("tickets_config", ctx.guild.id)
    panels = data.get("panels", [])
    new_panels = [p for p in panels if p["label"].lower() != label.lower()]
    if len(new_panels) == len(panels):
        return await ctx.send(embed=err(f"Type `{label}` introuvable."))
    data["panels"] = new_panels
    db_set("tickets_config", ctx.guild.id, data)
    await ctx.send(embed=ok(f"Type `{label}` supprimé."))

@cmd_ticket.command(name="types")
@is_admin()
async def ticket_types(ctx):
    """Voir les types de tickets configurés"""
    data = db_get("tickets_config", ctx.guild.id)
    panels = data.get("panels", [])
    if not panels:
        return await ctx.send(embed=em("Aucun type configuré.", color=cfg["color"]))
    desc = "\n".join(f"• {p.get('emoji','')} **{p['label']}** — {p.get('description','')}" for p in panels)
    await ctx.send(embed=em(desc, title="🎫 Types de tickets", color=cfg["color"]))

@cmd_ticket.command(name="setcategory")
@is_admin()
async def ticket_setcategory(ctx, *, category_id: str):
    """Définir la catégorie des tickets"""
    data = db_get("tickets_config", ctx.guild.id)
    data["category"] = category_id
    db_set("tickets_config", ctx.guild.id, data)
    await ctx.send(embed=ok("Catégorie des tickets définie."))

@cmd_ticket.command(name="setrole")
@is_admin()
async def ticket_setrole(ctx, role: discord.Role):
    """Définir le rôle modération pour les tickets"""
    data = db_get("tickets_config", ctx.guild.id)
    data["mod_role"] = str(role.id)
    db_set("tickets_config", ctx.guild.id, data)
    await ctx.send(embed=ok(f"Rôle modération tickets : **{role.name}**"))

@cmd_ticket.command(name="setlog")
@is_admin()
async def ticket_setlog(ctx, channel: discord.TextChannel):
    """Définir le salon de logs des tickets"""
    data = db_get("tickets_config", ctx.guild.id)
    data["log_channel"] = str(channel.id)
    db_set("tickets_config", ctx.guild.id, data)
    await ctx.send(embed=ok(f"Salon de logs tickets : {channel.mention}"))

@cmd_ticket.command(name="close")
async def ticket_close(ctx):
    """Fermer le ticket actuel"""
    if not ctx.channel.name.startswith("ticket-"):
        return await ctx.send(embed=err("Tu n'es pas dans un ticket."))
    await ctx.send(embed=warn("Fermeture dans 5s..."))
    await asyncio.sleep(5)
    await ctx.channel.delete()

# ────────────────────────────────────────────────────────────────────
#  ROLE MENU
# ────────────────────────────────────────────────────────────────────

class RoleButton(discord.ui.Button):
    def __init__(self, role: discord.Role):
        super().__init__(label=role.name, style=discord.ButtonStyle.secondary,
                         custom_id=f"rm_{role.id}")
        self.role_id = role.id

    async def callback(self, interaction: discord.Interaction):
        role = interaction.guild.get_role(self.role_id)
        if not role: return
        if role in interaction.user.roles:
            await interaction.user.remove_roles(role)
            await interaction.response.send_message(
                embed=ok(f"Rôle **{role.name}** retiré."), ephemeral=True)
        else:
            await interaction.user.add_roles(role)
            await interaction.response.send_message(
                embed=ok(f"Rôle **{role.name}** attribué."), ephemeral=True)

class RoleMenuView(discord.ui.View):
    def __init__(self, roles):
        super().__init__(timeout=None)
        for role in roles[:5]:
            self.add_item(RoleButton(role))

@bot.command(name="rolemenu")
@is_admin()
async def cmd_rolemenu(ctx, title: str, *roles: discord.Role):
    """Créer un menu de rôles avec boutons"""
    if not roles:
        return await ctx.send(embed=err("Spécifie au moins un rôle."))
    view = RoleMenuView(list(roles))
    await ctx.send(
        embed=em("Clique sur un bouton pour obtenir ou retirer un rôle.",
                 title=f"🏷️ {title}"),
        view=view)

# ────────────────────────────────────────────────────────────────────
#  GIVEAWAY
# ────────────────────────────────────────────────────────────────────

@bot.command(name="gstart")
@is_mod()
async def cmd_gstart(ctx, duration: str, winners: int, *, prize: str):
    """Lancer un giveaway (!gstart 1h 1 iPhone 15)"""
    secs = parse_duration(duration)
    if not secs:
        return await ctx.send(embed=err("Durée invalide. Ex: `1h`, `30m`"))
    end_time = time.time() + secs
    e = discord.Embed(
        title=f"🎉 GIVEAWAY — {prize}",
        description=f"Réagis avec 🎉 pour participer !\n"
                    f"Fin : <t:{int(end_time)}:R>\n"
                    f"Gagnants : **{winners}**",
        color=cfg["color"],
        timestamp=datetime.now(timezone.utc)
    )
    e.set_footer(text=f"Lancé par {ctx.author}")
    msg = await ctx.send(embed=e)
    await msg.add_reaction("🎉")
    gw_db = db_load("giveaways")
    gid = str(ctx.guild.id)
    gw_db.setdefault(gid, [])
    gw_db[gid].append({
        "message_id": msg.id, "channel_id": ctx.channel.id,
        "prize": prize, "winners": winners,
        "end_time": end_time, "ended": False
    })
    db_save("giveaways", gw_db)
    try: await ctx.message.delete()
    except: pass

@bot.command(name="greroll")
@is_mod()
async def cmd_greroll(ctx, message_id: int):
    """Relancer un giveaway"""
    for gw in db_load("giveaways").get(str(ctx.guild.id), []):
        if gw["message_id"] == message_id:
            ch = ctx.guild.get_channel(gw["channel_id"])
            try:
                msg = await ch.fetch_message(message_id)
                reaction = discord.utils.get(msg.reactions, emoji="🎉")
                participants = [u async for u in reaction.users() if not u.bot]
                if participants:
                    winner = random.choice(participants)
                    await ctx.send(embed=ok(
                        f"🎉 Nouveau gagnant : {winner.mention} pour **{gw['prize']}** !"))
                else:
                    await ctx.send(embed=err("Aucun participant."))
            except: await ctx.send(embed=err("Message introuvable."))
            return
    await ctx.send(embed=err("Giveaway introuvable."))

@bot.command(name="gend")
@is_mod()
async def cmd_gend(ctx, message_id: int):
    """Terminer un giveaway immédiatement"""
    gw_db = db_load("giveaways")
    gid = str(ctx.guild.id)
    for gw in gw_db.get(gid, []):
        if gw["message_id"] == message_id and not gw.get("ended"):
            gw["end_time"] = time.time() - 1
            db_save("giveaways", gw_db)
            return await ctx.send(embed=ok("Giveaway terminé — résultats dans quelques secondes."))
    await ctx.send(embed=err("Giveaway introuvable ou déjà terminé."))

# ────────────────────────────────────────────────────────────────────
#  TEMPVOC
# ────────────────────────────────────────────────────────────────────

@bot.command(name="tempvoc")
@is_admin()
async def cmd_tempvoc(ctx, action: str, channel: discord.VoiceChannel = None):
    """!tempvoc setup <salon>"""
    if action.lower() == "setup" and channel:
        data = db_get("tempvoc_config", ctx.guild.id)
        data["trigger_channel"] = str(channel.id)
        db_set("tempvoc_config", ctx.guild.id, data)
        await ctx.send(embed=ok(f"TempVoc configuré. Rejoins {channel.mention} pour créer un salon vocal."))
    else:
        await ctx.send(embed=em(f"Usage : `{cfg['prefix']}tempvoc setup <salon_déclencheur>`", color=cfg["color"]))

@bot.command(name="vcrename")
async def cmd_vcrename(ctx, *, name: str):
    """Renommer son salon vocal temporaire"""
    vc = ctx.author.voice.channel if ctx.author.voice else None
    if not vc or TEMPVOC_OWNERS.get(vc.id) != ctx.author.id:
        return await ctx.send(embed=err("Tu n'es pas propriétaire d'un tempvoc."))
    await vc.edit(name=name)
    await ctx.send(embed=ok(f"Salon renommé en **{name}**."))

@bot.command(name="vclimit")
async def cmd_vclimit(ctx, limit: int):
    """Modifier la limite d'utilisateurs de son tempvoc"""
    vc = ctx.author.voice.channel if ctx.author.voice else None
    if not vc or TEMPVOC_OWNERS.get(vc.id) != ctx.author.id:
        return await ctx.send(embed=err("Tu n'es pas propriétaire d'un tempvoc."))
    await vc.edit(user_limit=limit)
    await ctx.send(embed=ok(f"Limite de **{limit}** membre(s) appliquée."))

@bot.command(name="vclock")
async def cmd_vclock(ctx):
    """Verrouiller son salon vocal temporaire"""
    vc = ctx.author.voice.channel if ctx.author.voice else None
    if not vc or TEMPVOC_OWNERS.get(vc.id) != ctx.author.id:
        return await ctx.send(embed=err("Tu n'es pas propriétaire d'un tempvoc."))
    await vc.set_permissions(ctx.guild.default_role, connect=False)
    await ctx.send(embed=ok("Salon vocal verrouillé."))

@bot.command(name="vcunlock")
async def cmd_vcunlock(ctx):
    """Déverrouiller son salon vocal temporaire"""
    vc = ctx.author.voice.channel if ctx.author.voice else None
    if not vc or TEMPVOC_OWNERS.get(vc.id) != ctx.author.id:
        return await ctx.send(embed=err("Tu n'es pas propriétaire d'un tempvoc."))
    await vc.set_permissions(ctx.guild.default_role, connect=None)
    await ctx.send(embed=ok("Salon vocal déverrouillé."))

@bot.command(name="vckick")
async def cmd_vckick(ctx, member: discord.Member):
    """Expulser quelqu'un de son tempvoc"""
    vc = ctx.author.voice.channel if ctx.author.voice else None
    if not vc or TEMPVOC_OWNERS.get(vc.id) != ctx.author.id:
        return await ctx.send(embed=err("Tu n'es pas propriétaire d'un tempvoc."))
    await member.move_to(None)
    await ctx.send(embed=ok(f"**{member}** expulsé du vocal."))

# ────────────────────────────────────────────────────────────────────
#  INVITES
# ────────────────────────────────────────────────────────────────────

@bot.command(name="invites")
async def cmd_invites(ctx, member: discord.Member = None):
    """Voir le nombre d'invitations d'un membre"""
    m = member or ctx.author
    count = db_load("invites").get(str(ctx.guild.id), {}).get(str(m.id), 0)
    await ctx.send(embed=em(f"**{m}** a invité **{count}** membre(s).", color=cfg["color"]))

@bot.command(name="invlb", aliases=["invitetop"])
async def cmd_invlb(ctx):
    """Classement des invitations"""
    inv_db = db_load("invites").get(str(ctx.guild.id), {})
    if not inv_db:
        return await ctx.send(embed=err("Aucune donnée d'invite."))
    top = sorted(inv_db.items(), key=lambda x: x[1], reverse=True)[:10]
    desc = ""
    for i, (uid, count) in enumerate(top):
        m = ctx.guild.get_member(int(uid))
        name = str(m) if m else f"<{uid}>"
        desc += f"**#{i+1}** {name} — {count} invite(s)\n"
    await ctx.send(embed=em(desc, title="📩 Top Invites", color=cfg["color"]))

@bot.command(name="invitereward")
@is_admin()
async def cmd_invitereward(ctx, threshold: int, role: discord.Role):
    """Récompense pour un palier d'invitations"""
    data = db_get("invite_rewards", ctx.guild.id)
    data[str(threshold)] = str(role.id)
    db_set("invite_rewards", ctx.guild.id, data)
    await ctx.send(embed=ok(f"Rôle **{role.name}** attribué à {threshold} invite(s)."))

# ────────────────────────────────────────────────────────────────────
#  COMPTEURS
# ────────────────────────────────────────────────────────────────────

@bot.command(name="counter")
@is_admin()
async def cmd_counter(ctx, action: str, *, name: str = None):
    """!counter create <nom> | delete <nom> | list"""
    action = action.lower()
    if action == "create" and name:
        ch = await ctx.guild.create_voice_channel(f"📊 {name}: {ctx.guild.member_count}")
        data = db_get("counters", ctx.guild.id)
        data[str(ch.id)] = {"type": "members", "name": name}
        db_set("counters", ctx.guild.id, data)
        await ctx.send(embed=ok(f"Compteur créé : {ch.mention}"))
    elif action == "list":
        data = db_get("counters", ctx.guild.id)
        if not data:
            return await ctx.send(embed=ok("Aucun compteur."))
        desc = "\n".join(f"• <#{cid}> — {v['name']}" for cid, v in data.items())
        await ctx.send(embed=em(desc, title="📊 Compteurs", color=cfg["color"]))
    elif action == "delete" and name:
        data = db_get("counters", ctx.guild.id)
        for cid, v in list(data.items()):
            if v["name"] == name:
                ch = ctx.guild.get_channel(int(cid))
                if ch: await ch.delete()
                del data[cid]
                break
        db_set("counters", ctx.guild.id, data)
        await ctx.send(embed=ok("Compteur supprimé."))

# ────────────────────────────────────────────────────────────────────
#  EMBEDS
# ────────────────────────────────────────────────────────────────────

@bot.command(name="embed")
@is_mod()
async def cmd_embed(ctx, channel: discord.TextChannel = None, *, raw: str = ""):
    """!embed [#salon] titre :: description :: couleur_hex"""
    ch = channel or ctx.channel
    parts = [p.strip() for p in raw.split("::")]
    title = parts[0] if parts else "Embed"
    desc  = parts[1] if len(parts) > 1 else ""
    try:    color = int(parts[2].strip().lstrip("#"), 16) if len(parts) > 2 else cfg["color"]
    except: color = cfg["color"]
    try: await ctx.message.delete()
    except: pass
    await ch.send(embed=em(desc, title=title, color=color))

@bot.command(name="say")
@is_mod()
async def cmd_say(ctx, channel: discord.TextChannel = None, *, message: str):
    """Envoyer un message en tant que bot"""
    ch = channel or ctx.channel
    try: await ctx.message.delete()
    except: pass
    await ch.send(message)

@bot.command(name="announce")
@is_admin()
async def cmd_announce(ctx, channel: discord.TextChannel, *, message: str):
    """Envoyer une annonce avec mention @everyone"""
    try: await ctx.message.delete()
    except: pass
    e = em(message, title="📢 Annonce", color=cfg["color"])
    e.set_footer(text=f"Annoncé par {ctx.author}")
    await channel.send(content="@everyone", embed=e)

# ────────────────────────────────────────────────────────────────────
#  COMMANDES PERSO
# ────────────────────────────────────────────────────────────────────

@bot.command(name="addcmd")
@is_admin()
async def cmd_addcmd(ctx, name: str, *, response: str):
    """Créer une commande personnalisée"""
    data = db_get("custom_commands", ctx.guild.id)
    data[name.lower()] = response
    db_set("custom_commands", ctx.guild.id, data)
    await ctx.send(embed=ok(f"Commande `{cfg['prefix']}{name}` créée."))

@bot.command(name="delcmd")
@is_admin()
async def cmd_delcmd(ctx, name: str):
    """Supprimer une commande personnalisée"""
    data = db_get("custom_commands", ctx.guild.id)
    if name.lower() not in data:
        return await ctx.send(embed=err(f"Commande `{name}` introuvable."))
    del data[name.lower()]
    db_set("custom_commands", ctx.guild.id, data)
    await ctx.send(embed=ok(f"Commande `{name}` supprimée."))

@bot.command(name="listcmds")
async def cmd_listcmds(ctx):
    """Lister les commandes personnalisées"""
    data = db_get("custom_commands", ctx.guild.id)
    if not data:
        return await ctx.send(embed=em("Aucune commande personnalisée.", color=cfg["color"]))
    desc = "\n".join(f"• `{cfg['prefix']}{k}`" for k in sorted(data.keys()))
    await ctx.send(embed=em(desc, title="🔧 Commandes personnalisées", color=cfg["color"]))

# ────────────────────────────────────────────────────────────────────
#  CONFIGURATION
# ────────────────────────────────────────────────────────────────────

@bot.command(name="setlog")
@is_admin()
async def cmd_setlog(ctx, channel: discord.TextChannel):
    """Définir le salon de logs de modération"""
    cfg["mod_log_channel"] = str(channel.id)
    save_config(cfg)
    await ctx.send(embed=ok(f"Salon de logs : {channel.mention}"))

@bot.command(name="setwelcome")
@is_admin()
async def cmd_setwelcome(ctx, channel: discord.TextChannel = None, *, message: str = None):
    """Configurer le message de bienvenue"""
    wcfg = cfg["welcome"]
    if channel: wcfg["channel"] = str(channel.id); wcfg["enabled"] = True
    if message: wcfg["message"] = message
    save_config(cfg)
    await ctx.send(embed=ok(f"Bienvenue configuré.{' Salon: ' + channel.mention if channel else ''}"))

@bot.command(name="setwelcomerole")
@is_admin()
async def cmd_setwelcomerole(ctx, role: discord.Role):
    """Définir le rôle automatique à l'arrivée"""
    cfg["welcome"]["role"] = str(role.id)
    save_config(cfg)
    await ctx.send(embed=ok(f"Rôle de bienvenue : **{role.name}**"))

@bot.command(name="setgoodbye")
@is_admin()
async def cmd_setgoodbye(ctx, channel: discord.TextChannel = None, *, message: str = None):
    """Configurer le message d'au revoir"""
    gcfg = cfg["goodbye"]
    if channel: gcfg["channel"] = str(channel.id); gcfg["enabled"] = True
    if message: gcfg["message"] = message
    save_config(cfg)
    await ctx.send(embed=ok("Message d'au revoir configuré."))

@bot.command(name="welcometest")
@is_admin()
async def cmd_welcometest(ctx):
    """Tester le message de bienvenue"""
    await _do_welcome(ctx.author)
    await ctx.send(embed=ok("Message de bienvenue testé."), delete_after=3)

@bot.command(name="setprefix")
@is_admin()
async def cmd_setprefix(ctx, prefix: str):
    """Changer le préfixe du bot"""
    if len(prefix) > 3:
        return await ctx.send(embed=err("Préfixe trop long (max 3 caractères)."))
    cfg["prefix"] = prefix
    save_config(cfg)
    bot.command_prefix = commands.when_mentioned_or(prefix)
    await ctx.send(embed=ok(f"Préfixe changé en `{prefix}`"))

# ────────────────────────────────────────────────────────────────────
#  JEUX
# ────────────────────────────────────────────────────────────────────

@bot.command(name="pfc", aliases=["rps"])
async def cmd_pfc(ctx, choix: str):
    """Pierre Feuille Ciseaux"""
    choices = {"pierre": "🪨", "feuille": "📄", "ciseaux": "✂️",
               "rock": "🪨", "paper": "📄", "scissors": "✂️"}
    win_map = {"pierre": "ciseaux", "feuille": "pierre", "ciseaux": "feuille"}
    c = choix.lower()
    if c not in choices and c not in ("rock", "paper", "scissors"):
        return await ctx.send(embed=err("Choix invalide. `pierre`, `feuille` ou `ciseaux`"))
    if c in ("rock", "paper", "scissors"):
        c = {"rock": "pierre", "paper": "feuille", "scissors": "ciseaux"}[c]
    bot_choice = random.choice(["pierre", "feuille", "ciseaux"])
    if c == bot_choice:    result = "Égalité ! 🤝"
    elif win_map[c] == bot_choice: result = "Tu gagnes ! 🎉"
    else:                  result = "Tu perds ! 😢"
    await ctx.send(embed=em(
        f"Tu : {choices[c]} **{c}**\nMoi : {choices[bot_choice]} **{bot_choice}**\n\n**{result}**",
        color=cfg["color"]))

@bot.command(name="roll")
async def cmd_roll(ctx, dice: str = "1d6"):
    """Lancer des dés (ex: 2d20)"""
    try:
        n, s = map(int, dice.lower().split("d"))
        if not (1 <= n <= 20 and 2 <= s <= 100): raise ValueError
    except:
        return await ctx.send(embed=err("Format : `1d6`, `2d20`…"))
    results = [random.randint(1, s) for _ in range(n)]
    await ctx.send(embed=em(
        f"🎲 `{dice}` → {results} = **{sum(results)}**", color=cfg["color"]))

@bot.command(name="pile")
async def cmd_pile(ctx):
    """Pile ou face"""
    await ctx.send(embed=em(random.choice(["🪙 Pile !", "🪙 Face !"]), color=cfg["color"]))

@bot.command(name="8ball", aliases=["magic"])
async def cmd_8ball(ctx, *, question: str):
    """Boule magique"""
    reps = [
        "C'est certain ✅","Absolument ✅","Sans aucun doute ✅","Oui ✅",
        "Les signes disent oui ✅","Réponse floue 🤔","Réessaie 🤔",
        "Ne compte pas là-dessus ❌","Non ❌","Mes sources disent non ❌"
    ]
    await ctx.send(embed=em(
        f"🎱 {random.choice(reps)}", title=f"❓ {question[:100]}", color=cfg["color"]))

@bot.command(name="pendu")
async def cmd_pendu(ctx):
    """Lancer une partie de pendu"""
    MOTS_PENDU = [
        "python","discord","serveur","moderation","giveaway","ticket",
        "permission","antiraid","antispam","programmation","bot","nbots"
    ]
    word = random.choice(MOTS_PENDU).upper()
    pendu_games[ctx.channel.id] = {"word": word, "guessed": set(), "errors": 0}
    display = " ".join("_" * len(word))
    await ctx.send(embed=em(
        f"Mot : `{display}`\nErreurs : 0/7\n_Utilise `{cfg['prefix']}lettre <L>`_",
        title="🎯 Pendu", color=cfg["color"]))

pendu_games: dict[int, dict] = {}
PENDU_STAGES = ["😐","😬","😱","😨😰","😨😰✋","😨😰✋🦵","😨😰✋🦵✋","💀"]

@bot.command(name="lettre")
async def cmd_lettre(ctx, letter: str):
    """Proposer une lettre au pendu"""
    g = pendu_games.get(ctx.channel.id)
    if not g:
        return await ctx.send(embed=err(f"Pas de partie. Fais `{cfg['prefix']}pendu`"))
    L = letter[0].upper()
    if L in g["guessed"]:
        return await ctx.send(embed=warn("Lettre déjà proposée !"))
    g["guessed"].add(L)
    if L not in g["word"]:
        g["errors"] += 1
    display = " ".join(L if L in g["guessed"] else "_" for L in g["word"])
    stage = PENDU_STAGES[min(g["errors"], len(PENDU_STAGES)-1)]
    if all(L in g["guessed"] for L in g["word"]):
        del pendu_games[ctx.channel.id]
        return await ctx.send(embed=ok(f"🎉 Gagné ! Le mot était **{g['word']}** !"))
    if g["errors"] >= 7:
        del pendu_games[ctx.channel.id]
        return await ctx.send(embed=err(f"💀 Perdu ! Le mot était **{g['word']}**"))
    color = cfg["success_color"] if L in g["word"] else cfg["error_color"]
    await ctx.send(embed=em(
        f"{stage}\nMot : `{display}`\nErreurs : {g['errors']}/7\n"
        f"Lettres : {', '.join(sorted(g['guessed']))}",
        color=color))

rapido_active: dict[int, str] = {}
DEVINETTES = [
    ("J'ai des dents mais je ne mords pas. Qui suis-je ?", "peigne"),
    ("Plus je sèche, plus je suis mouillée. Qui suis-je ?", "serviette"),
    ("Je parle sans bouche, j'entends sans oreilles. Qui suis-je ?", "echo"),
    ("Je n'ai pas de jambes mais je peux courir. Qui suis-je ?", "eau"),
    ("Tout le monde me soulève, personne ne me porte longtemps. Qui suis-je ?", "probleme"),
]

@bot.command(name="rapido")
@is_mod()
async def cmd_rapido(ctx):
    """Lancer une devinette rapide"""
    q, a = random.choice(DEVINETTES)
    rapido_active[ctx.channel.id] = a.lower()
    await ctx.send(embed=em(f"❓ **{q}**\n_Sois le premier à répondre !_", color=cfg["color"]))

    def check(m):
        return m.channel == ctx.channel and not m.author.bot and ctx.channel.id in rapido_active

    try:
        while True:
            msg = await bot.wait_for("message", check=check, timeout=30)
            if msg.content.strip().lower() == rapido_active.get(ctx.channel.id, ""):
                del rapido_active[ctx.channel.id]
                return await ctx.send(embed=ok(f"🎉 {msg.author.mention} a trouvé !"))
    except asyncio.TimeoutError:
        ans = rapido_active.pop(ctx.channel.id, "?")
        await ctx.send(embed=err(f"Temps écoulé ! La réponse était **{ans}**."))

# ════════════════════════════════════════════════════════════════════
#  SLASH COMMANDS
# ════════════════════════════════════════════════════════════════════

@bot.tree.command(name="userinfo", description="Infos sur un membre")
@app_commands.describe(membre="Membre cible")
async def slash_userinfo(interaction: discord.Interaction, membre: discord.Member = None):
    m = membre or interaction.user
    roles = [r.mention for r in m.roles[1:]][:10]
    e = em(color=cfg["color"])
    e.set_author(name=str(m), icon_url=m.display_avatar.url)
    e.set_thumbnail(url=m.display_avatar.url)
    e.add_field(name="ID",          value=str(m.id))
    e.add_field(name="Compte créé", value=discord.utils.format_dt(m.created_at, "R"))
    e.add_field(name="A rejoint",   value=discord.utils.format_dt(m.joined_at,  "R"))
    e.add_field(name="Rôles",       value=" ".join(roles) or "Aucun", inline=False)
    await interaction.response.send_message(embed=e, ephemeral=True)

@bot.tree.command(name="warn", description="Avertir un membre")
@app_commands.describe(membre="Membre", raison="Raison")
async def slash_warn(interaction: discord.Interaction, membre: discord.Member,
                     raison: str = "Aucune raison"):
    if not interaction.user.guild_permissions.manage_messages:
        return await interaction.response.send_message(embed=err("Permission refusée."), ephemeral=True)
    warns = db_get("warns", interaction.guild.id)
    uid = str(membre.id)
    warns.setdefault(uid, [])
    warns[uid].append({"reason": raison, "by": str(interaction.user), "at": str(datetime.utcnow())})
    db_set("warns", interaction.guild.id, warns)
    await interaction.response.send_message(
        embed=ok(f"**{membre}** averti (total: {len(warns[uid])})."))

@bot.tree.command(name="clear", description="Supprimer des messages")
@app_commands.describe(nombre="Nombre de messages")
async def slash_clear(interaction: discord.Interaction, nombre: int = 10):
    if not interaction.user.guild_permissions.manage_messages:
        return await interaction.response.send_message(embed=err("Permission refusée."), ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=min(max(1, nombre), 500))
    await interaction.followup.send(embed=ok(f"{len(deleted)} message(s) supprimé(s)."), ephemeral=True)

@bot.tree.command(name="kick", description="Expulser un membre")
@app_commands.describe(membre="Membre", raison="Raison")
async def slash_kick(interaction: discord.Interaction, membre: discord.Member,
                     raison: str = "Aucune raison"):
    if not interaction.user.guild_permissions.kick_members:
        return await interaction.response.send_message(embed=err("Permission refusée."), ephemeral=True)
    await membre.kick(reason=raison)
    await interaction.response.send_message(embed=ok(f"**{membre}** expulsé."))

@bot.tree.command(name="ban", description="Bannir un membre")
@app_commands.describe(membre="Membre", raison="Raison")
async def slash_ban(interaction: discord.Interaction, membre: discord.Member,
                    raison: str = "Aucune raison"):
    if not interaction.user.guild_permissions.ban_members:
        return await interaction.response.send_message(embed=err("Permission refusée."), ephemeral=True)
    await membre.ban(reason=raison)
    await interaction.response.send_message(embed=ok(f"**{membre}** banni."))

@bot.tree.command(name="serverinfo", description="Infos sur le serveur")
async def slash_serverinfo(interaction: discord.Interaction):
    g = interaction.guild
    e = em(color=cfg["color"])
    e.set_author(name=g.name, icon_url=g.icon.url if g.icon else None)
    e.add_field(name="Membres", value=str(g.member_count))
    e.add_field(name="Salons",  value=str(len(g.channels)))
    e.add_field(name="Rôles",   value=str(len(g.roles)))
    e.add_field(name="Owner",   value=g.owner.mention if g.owner else "?")
    await interaction.response.send_message(embed=e)

# ════════════════════════════════════════════════════════════════════
#  AIDE
# ════════════════════════════════════════════════════════════════════

HELP_DATA = {
    "🔨 Modération": [
        ("warn <membre> [raison]",           "Avertir un membre"),
        ("warns <membre>",                   "Voir les warns"),
        ("clearwarns <membre>",              "Effacer les warns"),
        ("kick <membre> [raison]",           "Expulser"),
        ("ban <membre> [raison]",            "Bannir"),
        ("softban <membre> [raison]",        "Softban (nettoie les messages)"),
        ("tempban <membre> <durée> [raison]","Bannir temporairement"),
        ("unban <user#tag|id>",              "Débannir"),
        ("banlist",                          "Liste des bans"),
        ("mute <membre>",                    "Sourdine (28j)"),
        ("tempmute <membre> <durée>",        "Sourdine temporaire"),
        ("unmute <membre>",                  "Lever la sourdine"),
        ("unmuteall",                        "Démuter tout le monde"),
        ("mutelist",                         "Liste des mutés"),
        ("clear [n] [membre]",               "Supprimer des messages"),
        ("nick <membre> [surnom]",           "Changer le surnom"),
        ("derank <membre>",                  "Retirer tous les rôles"),
        ("addrole <membre> <rôle>",          "Ajouter un rôle"),
        ("delrole <membre> <rôle>",          "Retirer un rôle"),
        ("lock [salon]",                     "Verrouiller un salon"),
        ("unlock [salon]",                   "Déverrouiller"),
        ("hide [salon]",                     "Masquer un salon"),
        ("unhide [salon]",                   "Révéler un salon"),
        ("lockdown",                         "Activer/désactiver le lockdown"),
        ("announce <#salon> <msg>",          "Envoyer une annonce @everyone"),
    ],
    "🔍 Infos": [
        ("note <membre> <note>",             "Ajouter une note"),
        ("notes <membre>",                   "Voir les notes"),
        ("userinfo [membre]",                "Infos sur un membre"),
        ("serverinfo",                       "Infos sur le serveur"),
        ("avatar [membre]",                  "Afficher un avatar"),
        ("banner [membre]",                  "Afficher une bannière"),
        ("roleinfo <rôle>",                  "Infos sur un rôle"),
        ("members [rôle]",                   "Membres d'un rôle"),
    ],
    "🛡️ Anti-Raid / Spam": [
        ("antiraid [action] [val]",          "Configurer l'anti-raid"),
        ("antispam [action] [val]",          "Configurer l'antispam"),
        ("automod <action> [mot]",           "Filtre de mots"),
        ("invitefilter <enable|disable>",    "Filtrer les invitations"),
    ],
    "✅ WL / BL": [
        ("wl",                               "Voir la whitelist"),
        ("wl add <membre>",                  "Ajouter à la WL"),
        ("wl remove <membre>",               "Retirer de la WL"),
        ("wl clear",                         "Vider la WL"),
        ("bl",                               "Voir la blacklist"),
        ("bl add <membre> [raison]",         "Blacklister un membre"),
        ("bl remove <membre>",               "Retirer de la BL"),
        ("bl clear",                         "Vider la BL"),
    ],
    "🔐 Perms par rôle": [
        ("roleperm",                         "Voir les permissions"),
        ("roleperm add <rôle> <cmds...>",    "Ajouter accès commandes"),
        ("roleperm remove <rôle> <cmds...>", "Retirer accès"),
        ("roleperm reset [rôle]",            "Réinitialiser"),
        ("roleperm check <membre> <cmd>",    "Vérifier l'accès"),
    ],
    "🎫 Tickets": [
        ("ticket panel [titre]",             "Panneau d'ouverture"),
        ("ticket addtype <label> <emoji> [desc]", "Ajouter un type de ticket"),
        ("ticket removetype <label>",        "Supprimer un type"),
        ("ticket types",                     "Voir les types"),
        ("ticket setcategory <id>",          "Catégorie des tickets"),
        ("ticket setrole <@rôle>",           "Rôle modération"),
        ("ticket setlog <#salon>",           "Salon de logs tickets"),
        ("ticket close",                     "Fermer le ticket actuel"),
    ],
    "🏷️ Rolemenu": [
        ("rolemenu <titre> <rôles...>",      "Menu de rôles avec boutons"),
    ],
    "🎉 Giveaway": [
        ("gstart <durée> <n> <prix>",        "Lancer un giveaway"),
        ("greroll <msg_id>",                 "Relancer un giveaway"),
        ("gend <msg_id>",                    "Terminer immédiatement"),
    ],
    "🎙️ TempVoc": [
        ("tempvoc setup <salon>",            "Configurer le déclencheur"),
        ("vcrename <nom>",                   "Renommer son salon"),
        ("vclimit <n>",                      "Modifier la limite"),
        ("vclock / vcunlock",                "Verrouiller / déverrouiller"),
        ("vckick <membre>",                  "Expulser du vocal"),
    ],
    "📩 Invites": [
        ("invites [membre]",                 "Voir ses invitations"),
        ("invlb",                            "Classement invites"),
        ("invitereward <palier> <rôle>",     "Récompense d'invitation"),
    ],
    "📊 Compteurs": [
        ("counter create <nom>",             "Créer un compteur"),
        ("counter list",                     "Voir les compteurs"),
        ("counter delete <nom>",             "Supprimer un compteur"),
    ],
    "🖼️ Embeds": [
        ("embed [#salon] titre::desc::hex",  "Créer un embed"),
        ("say [#salon] <message>",           "Envoyer un message"),
        ("announce <#salon> <message>",      "Annonce @everyone"),
    ],
    "🔧 Commandes perso": [
        ("addcmd <nom> <réponse>",           "Créer une commande"),
        ("delcmd <nom>",                     "Supprimer une commande"),
        ("listcmds",                         "Lister les commandes"),
    ],
    "🎮 Jeux": [
        ("pfc <pierre|feuille|ciseaux>",     "Pierre Feuille Ciseaux"),
        ("pendu",                            "Pendu (deviner le mot)"),
        ("lettre <L>",                       "Proposer une lettre"),
        ("roll [XdY]",                       "Lancer des dés"),
        ("pile",                             "Pile ou face"),
        ("8ball <question>",                 "Boule magique"),
        ("rapido",                           "Devinette rapide"),
    ],
    "⚙️ Configuration": [
        ("setlog <#salon>",                  "Salon de logs"),
        ("setprefix <préfixe>",              "Changer le préfixe"),
        ("setwelcome <#salon> [msg]",        "Message de bienvenue"),
        ("setwelcomerole <@rôle>",           "Rôle de bienvenue"),
        ("setgoodbye <#salon> [msg]",        "Message d'au revoir"),
        ("welcometest",                      "Tester le message de bienvenue"),
    ],
}

class HelpSelect(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label=cat, value=cat) for cat in HELP_DATA]
        super().__init__(placeholder="📚 Choisis une catégorie…", options=options, min_values=1)

    async def callback(self, interaction: discord.Interaction):
        cat = self.values[0]
        cmds = HELP_DATA[cat]
        desc = "\n".join(f"`{cfg['prefix']}{name}` — {desc}" for name, desc in cmds)
        bot_name = cfg.get("bot_name", "NBots")
        e = em(desc, title=cat, color=cfg["color"])
        e.set_footer(text=f"{bot_name} | {cfg['prefix']}help")
        await interaction.response.edit_message(embed=e)

class HelpView(discord.ui.View):
    def __init__(self): super().__init__(timeout=120); self.add_item(HelpSelect())

@bot.command(name="help", aliases=["h", "aide"])
async def cmd_help(ctx, *, category: str = None):
    """Menu d'aide interactif"""
    bot_name = cfg.get("bot_name", "NBots")
    if category:
        for cat, cmds in HELP_DATA.items():
            if category.lower() in cat.lower():
                desc = "\n".join(f"`{cfg['prefix']}{name}` — {d}" for name, d in cmds)
                return await ctx.send(embed=em(desc, title=cat, color=cfg["color"]))
        return await ctx.send(embed=err("Catégorie introuvable."))
    cats = "\n".join(f"{cat} — **{len(cmds)}** commandes" for cat, cmds in HELP_DATA.items())
    e = em(cats, title=f"📚 {bot_name} — Aide complète", color=cfg["color"])
    e.set_footer(text=f"Préfixe : {cfg['prefix']} | Utilise le menu ci-dessous")
    await ctx.send(embed=e, view=HelpView())

# ════════════════════════════════════════════════════════════════════
#  LANCEMENT
# ════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    token = cfg.get("token", "")
    if not token or token == "TON_TOKEN_ICI":
        print("❌  Remplis ton token dans config.json avant de lancer le bot !")
        exit(1)
    bot.run(token, log_handler=None)
