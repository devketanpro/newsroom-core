from typing import cast
from superdesk.core import get_current_app


def get_current_wsgi_app():
    from newsroom.web.factory import NewsroomWebApp

    return cast(NewsroomWebApp, get_current_app())