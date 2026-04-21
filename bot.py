import discord
from discord.ext import commands
import asyncio
import os
from datetime import datetime, timedelta

# ========= CONFIGURACIÓN =========
TOKEN = os.getenv("TOKEN")
DURACION_SEGUNDOS = 60           # 1 minuto para pruebas (cambia a 3 * 24 * 60 * 60 para 3 días)
CATEGORIA_NOMBRE = "Tickets"     # Nombre de la categoría donde se crearán los canales
# =================================

# {user_id: {"channel_id": int, "task": asyncio.Task}}
tickets_activos = {}

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


# ---------- Buscar o crear categoría ----------
async def obtener_categoria(guild: discord.Guild) -> discord.CategoryChannel:
    categoria = discord.utils.get(guild.categories, name=CATEGORIA_NOMBRE)
    if categoria is None:
        categoria = await guild.create_category(CATEGORIA_NOMBRE)
    return categoria


# ---------- Vista dentro del canal privado (activo) ----------
class TicketActivoView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Eliminar canal",
        style=discord.ButtonStyle.danger,
        emoji="🗑️",
        custom_id="ticket_eliminar",
    )
    async def eliminar(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        if user_id in tickets_activos:
            task = tickets_activos[user_id].get("task")
            if task:
                task.cancel()
            tickets_activos.pop(user_id, None)
        await interaction.response.send_message("Eliminando canal...", ephemeral=True)
        await asyncio.sleep(2)
        await interaction.channel.delete()


# ---------- Vista del aviso final (reiniciar o eliminar) ----------
class AvisoFinalView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=None)
        self.user_id = user_id

    @discord.ui.button(
        label="Reiniciar contador",
        style=discord.ButtonStyle.primary,
        emoji="🔄",
        custom_id="ticket_reiniciar",
    )
    async def reiniciar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Este botón no es para ti.", ephemeral=True)
            return

        user_id = interaction.user.id
        fin_dt = datetime.utcnow() + timedelta(seconds=DURACION_SEGUNDOS)
        fin_ts = fin_dt.timestamp()

        # Cancelar tarea anterior si existe
        if user_id in tickets_activos:
            task = tickets_activos[user_id].get("task")
            if task:
                task.cancel()

        tickets_activos[user_id] = {
            "channel_id": interaction.channel.id,
            "task": None,
        }

        await interaction.response.edit_message(
            content=f"🔄 Contador reiniciado. Te avisaré <t:{int(fin_ts)}:R>.",
            view=TicketActivoView()
        )

        task = bot.loop.create_task(
            temporizador_canal(user_id, interaction.channel.id, fin_ts, DURACION_SEGUNDOS)
        )
        tickets_activos[user_id]["task"] = task

    @discord.ui.button(
        label="Eliminar canal",
        style=discord.ButtonStyle.danger,
        emoji="🗑️",
        custom_id="ticket_eliminar_final",
    )
    async def eliminar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Este botón no es para ti.", ephemeral=True)
            return

        user_id = interaction.user.id
        if user_id in tickets_activos:
            task = tickets_activos[user_id].get("task")
            if task:
                task.cancel()
            tickets_activos.pop(user_id, None)

        await interaction.response.send_message("Eliminando canal...", ephemeral=True)
        await asyncio.sleep(2)
        await interaction.channel.delete()


# ---------- Temporizador dentro del canal ----------
async def temporizador_canal(user_id: int, channel_id: int, fin_ts: float, segundos: float):
    try:
        await asyncio.sleep(segundos)

        if user_id not in tickets_activos:
            return

        canal = bot.get_channel(channel_id)
        if canal is None:
            tickets_activos.pop(user_id, None)
            return

        await canal.send(
            f"<@{user_id}> ✅ ya puedes comprar cargadores!\n¿Qué quieres hacer?",
            view=AvisoFinalView(user_id)
        )

    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"Error en temporizador de {user_id}: {e}")


# ---------- Vista del panel principal ----------
class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Abrir ticket",
        style=discord.ButtonStyle.primary,
        emoji="🎫",
        custom_id="ticket_boton_cargadores",
    )
    async def abrir_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        guild = interaction.guild

        # Si ya tiene canal activo
        if user_id in tickets_activos:
            channel_id = tickets_activos[user_id]["channel_id"]
            canal = bot.get_channel(channel_id)
            if canal:
                await interaction.response.send_message(
                    f"⏳ Ya tienes un ticket activo: {canal.mention}",
                    ephemeral=True,
                )
                return
            else:
                tickets_activos.pop(user_id)

        await interaction.response.defer(ephemeral=True)

        # Crear canal privado
        categoria = await obtener_categoria(guild)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        }

        nombre_canal = f"cargadores-{interaction.user.name}".lower().replace(" ", "-")[:32]
        canal = await categoria.create_text_channel(nombre_canal, overwrites=overwrites)

        fin_dt = datetime.utcnow() + timedelta(seconds=DURACION_SEGUNDOS)
        fin_ts = fin_dt.timestamp()

        tickets_activos[user_id] = {
            "channel_id": canal.id,
            "task": None,
        }

        await canal.send(
            f"👋 Hola {interaction.user.mention}!\n"
            f"Tu ticket ha sido creado. Te avisaré aquí <t:{int(fin_ts)}:R> (el <t:{int(fin_ts)}:F>) cuando puedas comprar cargadores.",
            view=TicketActivoView()
        )

        task = bot.loop.create_task(
            temporizador_canal(user_id, canal.id, fin_ts, DURACION_SEGUNDOS)
        )
        tickets_activos[user_id]["task"] = task

        await interaction.followup.send(f"✅ Canal creado: {canal.mention}", ephemeral=True)


# ---------- Embed ----------
def hacer_embed():
    return discord.Embed(
        title="🎫 Sistema de tickets — Cargadores",
        description=(
            "Pulsa el botón para abrir tu ticket.\n"
            "Se creará un canal privado con tu contador.\n"
            "Cuando puedas comprar cargadores te avisaremos ahí."
        ),
        color=discord.Color.blurple(),
    )


# ---------- On ready ----------
@bot.event
async def on_ready():
    bot.add_view(TicketView())
    bot.add_view(TicketActivoView())
    try:
        synced = await bot.tree.sync()
        print(f"Slash commands sincronizados: {len(synced)}")
    except Exception as e:
        print(f"Error sincronizando: {e}")
    print(f"Bot conectado como {bot.user}")


# ---------- !cargador ----------
@bot.command(name="cargador")
@commands.has_permissions(manage_guild=True)
async def cargador(ctx):
    await ctx.send(embed=hacer_embed(), view=TicketView())


bot.run(TOKEN)
