"""Discord direct messages through aa-discordbot (optional)."""

from django.apps import apps

from ..models import TicketSettings


def bot_installed():
    return apps.is_installed("aadiscordbot")


def is_available():
    return bot_installed() and TicketSettings.get_solo().discord_dm_enabled


def send(user_pk, title, description, url):
    """Queue a DM through aa-discordbot. Raises if the bot cannot take it."""
    from discord import Embed

    from aadiscordbot.tasks import send_message

    embed = Embed(title=title[:256], description=description, url=url)
    send_message(user_pk=user_pk, embed=embed)
