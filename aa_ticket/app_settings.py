"""Fixed values used across the app. Admin-editable settings live in TicketSettings."""

MAX_IMAGES_PER_MESSAGE = 5
MAX_IMAGE_PIXELS = 25_000_000  # larger images are refused before decoding (memory on small servers)
MAX_IMAGE_EDGE = 4096  # longer edges are scaled down to this when the image is saved
MAX_FRAMES = 100
MAX_ANIMATION_PIXELS = 100_000_000  # frames x width x height
BADGE_CACHE_SECONDS = 60
CARD_CACHE_SECONDS = 30
UNCLAIMED_REPLY_NOTICE_SECONDS = 3600
LIST_PAGE_SIZE = 50
ORPHAN_FILE_MIN_AGE_SECONDS = 86400


def unclaimed_reply_key(ticket_id):
    """Cache key that limits "requester added a reply" channel notices to one per hour and ticket."""
    return f"aa_ticket:unclaimed_reply:{ticket_id}"
WEBHOOK_TIMEOUT = 10
WEBHOOK_TEST_TIMEOUT = 5
WEBHOOK_MAX_RETRIES = 5
