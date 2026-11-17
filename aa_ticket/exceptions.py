class TicketActionError(Exception):
    """An action could not be done; `message` is a translated, user-facing text."""

    def __init__(self, message):
        super().__init__(str(message))
        self.message = str(message)
