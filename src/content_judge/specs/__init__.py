from .blog_error import BLOG_ERROR
from .x_reply import X_REPLY
from . import content_potential

SPEC_BY_KIND = {
    "blog_error": BLOG_ERROR,
    "x_reply": X_REPLY,
}

__all__ = [
    "BLOG_ERROR",
    "X_REPLY",
    "content_potential",
    "SPEC_BY_KIND",
]

