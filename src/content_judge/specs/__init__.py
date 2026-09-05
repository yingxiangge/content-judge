from .blog_error import BLOG_ERROR
from .x_reply import X_REPLY
from .video_topic import VIDEO_SPEC_TOPIC
from . import content_potential

# 🔴 **形态 → spec 的唯一注册表**。调用方一律经这里取，取不到就是**没有质检**，
#    **不许回落到别的形态的 spec** —— 09-01 那次正是「topic 取不到 → 回落 daily」，
#    而 daily 那份当时已被删，`SPEC_BY_KIND["daily"]` 直接 KeyError 被上游吞掉，
#    质检静默空转 4 天没人发现（详见 `video_topic.py` 文件头）。
#    ⚠️ 判据一律住 `specs/`，业务仓只做编排（铁律 #1，同 09-04 x_reply v6 的处理）。
SPEC_BY_KIND = {
    "blog_error": BLOG_ERROR,
    "x_reply": X_REPLY,
    "topic": VIDEO_SPEC_TOPIC,
}

__all__ = [
    "BLOG_ERROR",
    "X_REPLY",
    "VIDEO_SPEC_TOPIC",
    "content_potential",
    "SPEC_BY_KIND",
]
