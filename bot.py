import discord
from discord.ext import commands
import asyncio
import os
from datetime import datetime, timedelta

# ========= CONFIGURACIÓN =========
TOKEN = os.getenv("TOKEN")
DURACION_SEGUNDOS = 3 * 24 * 60 * 60   # 1 minuto para pruebas
# =================================

# {user_id: {"fin": fin_ts, "channel_id": int, "confirm_msg_id": int}}
tickets_activos = {}

# {user_id: message_id} — ID del aviso final para borrarlo al pulsar el botón
avisos_pendientes = {}

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


# ---------- Vista del aviso final (con botón para nuevo ticket) ----------
class AvisoView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=None)
        self.user_id = user_id

    @discord.ui.button(
        label="Abrir nuevo ticket",
        style=discord.ButtonStyle.success,
        emoji="🎫",
        custom_id="ticket_boton_nuevo",
    )
    async def nuevo_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id

        # Solo el usuario al que va el aviso puede pulsarlo
        if user_id != self.user_id:
            await interaction.response.send_message(
                "❌ Este botón no es para ti.",
                ephemeral=True,
            )
            return

        # Si ya tiene ticket activo
        if user_id in tickets_activos:
            fin_ts = tickets_activos[user_id]["fin"]
            await interaction.response.send_message(
                f"⏳ Ya tienes un ticket activo. Termina <t:{int(fin_ts)}:R>.",
                ephemeral=True,
            )
            return

        # Borrar el aviso
        try:
            await interaction.message.delete()
        except Exception:
            pass
        avisos_pendientes.pop(user_id, None)

        # Crear nuevo ticket
        fin_dt = datetime.utcnow() + timedelta(seconds=DURACION_SEGUNDOS)
        fin_ts = fin_dt.timestamp()

        await interaction.response.send_message(
            f"🎫 Ticket creado para {interaction.user.mention}.\n"
            f"Te avisaré aquí <t:{int(fin_ts)}:R> (el <t:{int(fin_ts)}:F>).",
        )
        msg = await interaction.original_response()

        tickets_activos[user_id] = {
            "fin": fin_ts,
            "channel_id": interaction.channel.id,
            "confirm_msg_id": msg.id,
        }

        bot.loop.create_task(
            iniciar_temporizador(user_id, interaction.channel.id, msg.id, DURACION_SEGUNDOS)
        )


# ---------- Temporizador ----------
async def iniciar_temporizador(user_id: int, channel_id: int, confirm_msg_id: int, segundos: float):
    try:
        if segundos > 0:
            await asyncio.sleep(segundos)

        if user_id not in tickets_activos:
            return

        canal = bot.get_channel(channel_id)
        if canal is None:
            try:
                canal = await bot.fetch_channel(channel_id)
            except Exception:
                tickets_activos.pop(user_id, None)
                return

        # Borrar mensaje de confirmación "Ticket creado para..."
        try:
            confirm_msg = await canal.fetch_message(confirm_msg_id)
            await confirm_msg.delete()
        except Exception:
            pass

        # Enviar aviso con botón para nuevo ticket
        aviso = await canal.send(
            f"<@{user_id}> ya puedes comprar cargadores ✅",
            view=AvisoView(user_id)
        )
        avisos_pendientes[user_id] = aviso.id

    except Exception as e:
        print(f"Error en temporizador de {user_id}: {e}")
    finally:
        tickets_activos.pop(user_id, None)


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

        if user_id in tickets_activos:
            fin_ts = tickets_activos[user_id]["fin"]
            await interaction.response.send_message(
                f"⏳ Ya tienes un ticket activo. Termina <t:{int(fin_ts)}:R>.",
                ephemeral=True,
            )
            return

        # Borrar aviso pendiente si existe
        if user_id in avisos_pendientes:
            try:
                msg_aviso = await interaction.channel.fetch_message(avisos_pendientes[user_id])
                await msg_aviso.delete()
            except Exception:
                pass
            avisos_pendientes.pop(user_id, None)

        fin_dt = datetime.utcnow() + timedelta(seconds=DURACION_SEGUNDOS)
        fin_ts = fin_dt.timestamp()

        await interaction.response.send_message(
            f"🎫 Ticket creado para {interaction.user.mention}.\n"
            f"Te avisaré aquí <t:{int(fin_ts)}:R> (el <t:{int(fin_ts)}:F>).",
        )
        msg = await interaction.original_response()

        tickets_activos[user_id] = {
            "fin": fin_ts,
            "channel_id": interaction.channel.id,
            "confirm_msg_id": msg.id,
        }

        bot.loop.create_task(
            iniciar_temporizador(user_id, interaction.channel.id, msg.id, DURACION_SEGUNDOS)
        )


# ---------- Embed ----------
def hacer_embed():
    return discord.Embed(
        title="🎫 Sistema de tickets — Cargadores",
        description=(
            "Pulsa el botón para abrir tu ticket.\n"
            "Se iniciará un contador y te avisaré aquí "
            "cuando ya puedas comprar cargadores."
        ),
        color=discord.Color.blurple(),
    )


# ---------- On ready ----------
@bot.event
async def on_ready():
    bot.add_view(TicketView())
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


# ---------- !reset ----------
@bot.command(name="reset")
async def reset(ctx):
    user_id = ctx.author.id
    if user_id in tickets_activos:
        tickets_activos.pop(user_id)
        avisos_pendientes.pop(user_id, None)
        await ctx.send("✅ Ticket reseteado.", delete_after=5)
    else:
        await ctx.send("No tienes ningún ticket activo.", delete_after=5)


bot.run(TOKEN)
