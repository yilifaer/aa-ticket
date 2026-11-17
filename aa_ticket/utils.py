def display_name(user):
    """Main character name, falling back to the username."""
    if user is None:
        return ""
    profile = getattr(user, "profile", None)
    character = getattr(profile, "main_character", None) if profile else None
    if character is not None:
        return character.character_name
    return user.username
