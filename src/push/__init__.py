"""推送平台模块"""

from typing import Optional

from src.config import ConfigModel, get_config

from .base import PushPlatform
from .discord import DiscordPlatform
from .feishu import FeishuPlatform
from .gmail import GmailPlatform

PLATFORM_CLASSES = {
    "discord": DiscordPlatform,
    "feishu": FeishuPlatform,
    "gmail": GmailPlatform,
}


def create_platform(name: str, config: ConfigModel) -> Optional[PushPlatform]:
    """工厂函数，创建推送平台实例；环境变量未就绪时返回 None"""
    if name not in PLATFORM_CLASSES:
        raise ValueError(f"未知推送平台: {name}")

    platform = PLATFORM_CLASSES[name](config)
    return platform if platform.is_ready() else None


async def send_to_platforms(content: str, title: str = None):
    """发送内容到所有已启用且环境变量就绪的平台"""
    push_config = get_config().push
    for platform_name, platform_conf in push_config.enabled_platforms().items():
        platform = create_platform(platform_name, platform_conf)
        if platform is None:
            continue

        try:
            await platform.send(content, title)
            print(f"✅ 已推送到 {platform_name}")
        except Exception as e:
            print(f"❌ 推送到 {platform_name} 失败: {e}")
