from flask import Blueprint

student_points_bp = Blueprint(
    "student_points",
    __name__,
    url_prefix="/poin-siswa",
    template_folder="templates",
)

from . import routes  # noqa: E402,F401
