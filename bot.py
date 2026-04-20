import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import json
import os
from datetime import datetime, timedelta

# ========= CONFIGURACIÓN =========
TOKEN = "PON_AQUI_TU_TOKEN"   # Token del bot (https://discord.com/developers/applications)
DURACION_SEGUNDOS = 3 * 24 * 60 * 60   # 3 días. Para pruebas puedes poner 60 (1 minuto)
ARCHIVO_DATOS = "tickets.json"         # Para que los timers sobrevivan reinicios
# =================================

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


# ---------- Persistencia ----------
def cargar_tickets():
    if not os.path.exists(ARCHIVO_DATOS):
        return {}
    try:
        with open(ARCHIVO_DATOS, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def guardar_tickets(data):
    with open(ARCHIVO_DATOS, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def añadir_ticket(user_id, channel_id, fin_ts):
    data = cargar_tickets()
    data[str(user_id)] = {"channel_id": channel_id, "fin": fin_ts}
    guardar_tickets(data)


def eliminar_ticket(user_id):
    data = cargar_tickets()
    data.pop(str(user_id), None)
    guardar_tickets(data)


# ---------- Lógica del temporizador ----------
async def iniciar_temporizador(user_id: int, channel_id: int, segundos_restantes: float):
    """Espera el tiempo indicado y luego avisa al usuario en el canal."""
    try:
        if segundos_restantes > 0:
            await asyncio.sleep(segundos_restantes)

        canal = bot.get_channel(channel_id)
        if canal is None:
            try:
                canal = await bot.fetch_channel(channel_id)
            except Exception:
                eliminar_ticket(user_id)
                return

        await canal.send(f"<@{user_id}> ya puedes comprar cargadores ✅")
    except Exception as e:
        print(f"Error en temporizador de {user_id}: {e}")
    finally:
        eliminar_ticket(user_id)


# ---------- Vista con el botón (persistente) ----------
class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # Persistente tras reinicios

    @discord.ui.button(
        label="Abrir ticket",
        style=discord.ButtonStyle.primary,
        emoji="🎫",
        custom_id="ticket_boton_cargadores",
    )
    async def abrir_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        tickets = cargar_tickets()
        user_id = str(interaction.user.id)

        # Evitar dobles clics del mismo usuario
        if user_id in tickets:
            fin = datetime.fromtimestamp(tickets[user_id]["fin"])
            await interaction.response.send_message(
                f"⏳ Ya tienes un ticket activo. Termina <t:{int(fin.timestamp())}:R>.",
                ephemeral=True,
            )
            return

        fin_dt = datetime.utcnow() + timedelta(seconds=DURACION_SEGUNDOS)
        fin_ts = fin_dt.timestamp()

        añadir_ticket(interaction.user.id, interaction.channel.id, fin_ts)

        await interaction.response.send_message(
            f"🎫 Ticket creado para {interaction.user.mention}.\n"
            f"Te avisaré aquí <t:{int(fin_ts)}:R> (el <t:{int(fin_ts)}:F>).",
            ephemeral=False,
        )

        bot.loop.create_task(
            iniciar_temporizador(interaction.user.id, interaction.channel.id, DURACION_SEGUNDOS)
        )


# ---------- Eventos ----------
@bot.event
async def on_ready():
    bot.add_view(TicketView())  # Registra la vista persistente

    # Reanudar timers que estaban en marcha antes de reiniciar el bot
    data = cargar_tickets()
    ahora = datetime.utcnow().timestamp()
    for user_id, info in list(data.items()):
        restante = info["fin"] - ahora
        if restante <= 0:
            bot.loop.create_task(iniciar_temporizador(int(user_id), info["channel_id"], 0))
        else:
            bot.loop.create_task(iniciar_temporizador(int(user_id), info["channel_id"], restante))

    try:
        synced = await bot.tree.sync()
        print(f"Slash commands sincronizados: {len(synced)}")
    except Exception as e:
        print(f"Error sincronizando: {e}")

    print(f"Bot conectado como {bot.user}")


# ---------- Comando para publicar el panel con el botón ----------
@bot.tree.command(name="panel", description="Publica el panel con el botón de ticket")
@app_commands.default_permissions(manage_guild=True)
async def panel(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🎫 Sistema de tickets — Cargadores",
        description=(
            "Pulsa el botón para abrir tu ticket.\n"
            "Se iniciará un contador de **3 días** y te avisaré aquí "
            "cuando ya puedas comprar cargadores."
        ),
        color=discord.Color.blurple(),
    )
    await interaction.channel.send(embed=embed, view=TicketView())
    await interaction.response.send_message("Panel publicado ✅", ephemeral=True)


bot.run(TOKEN)
