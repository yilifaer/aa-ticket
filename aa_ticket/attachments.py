"""Image attachments: validation, storage and clean-up."""


def delete_attachment(attachment):
    """Delete the file from storage and the database row."""
    if attachment.file:
        attachment.file.delete(save=False)
    attachment.delete()
