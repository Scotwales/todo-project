from .release import APP_NAME, APP_VERSION
from .user_settings import read_preferences


def application_context(request):
    preferences = read_preferences()
    return {
        "app_name": APP_NAME,
        "app_version": APP_VERSION,
        "app_theme": preferences.get("theme", request.session.get("theme", "light")),
    }
