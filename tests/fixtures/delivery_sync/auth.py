VALID_TOKENS = {"secret-token": "driver-1"}


def authenticate_user(token):
    """Authenticate an API request by bearer token and return the user id."""
    user = VALID_TOKENS.get(token)
    if user is None:
        raise PermissionError("invalid token")
    return user
