"""Discord direct messages through aa-discordbot (optional)."""

from django.apps import apps

from ..models import TicketSettings


def bot_installed():
    return apps.is_installed("aadiscordbot")


def is_available():
    return bot_installed() and TicketSettings.get_solo().discord_dm_enabled


def send(user_pk, title, description, url, fields=()):
    """Queue a DM through aa-discordbot. Raises if the bot cannot take it.

    fields: (name, value) pairs shown under the text, e.g. department and assignee.
    """
    from discord import Embed

    from aadiscordbot.tasks import send_message

    embed = Embed(title=title[:256], description=description, url=url)
    for name, value in fields:
        embed.add_field(name=name[:256], value=value[:1024], inline=True)
    send_message(user_pk=user_pk, embed=embed)
