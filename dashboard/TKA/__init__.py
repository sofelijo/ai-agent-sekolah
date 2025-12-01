from flask import Blueprint

tka_bp = Blueprint(
    "tka",
    __name__,
    template_folder="templates",
)

from . import routes
