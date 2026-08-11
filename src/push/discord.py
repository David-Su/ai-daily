"""Discord推送平台"""

import os

import aiohttp

from src.config import WebhookPushConfig

from .base import PushPlatform


WEBHOOK_URL_PREFIX = "https://discord.com/api/webhooks/"


class DiscordPlatform(PushPlatform):
    """Discord Webhook推送"""

    def __init__(self, config: WebhookPushConfig):
        super().__init__(config)
        self.webhook_url = os.environ.get(config.apiKeyName, "")

    def is_ready(self) -> bool:
        """检查 Webhook 环境变量是否为合法的 Discord 地址"""
        if not self.webhook_url.startswith(WEBHOOK_URL_PREFIX):
            print(f"⚠️ Discord 跳过推送: {self.config.apiKeyName} 未设置或不是合法的 Webhook 地址")
            return False
        return True

    async def send(self, content: str, title: str = None):
        """发送到Discord"""
        chunks = self._split_content(content, limit=2000)

        async with aiohttp.ClientSession() as session:
            for chunk in chunks:
                payload = {"content": chunk}
                async with session.post(self.webhook_url, json=payload) as resp:
                    if resp.status != 204:
                        text = await resp.text()
                        raise RuntimeError(f"Discord推送失败: {resp.status} - {text}")

    def _split_content(self, content: str, limit: int = 2000) -> list:
        """Discord限制2000字符，需要分割"""
        if len(content) <= limit:
            return [content]

        chunks = []
        lines = content.split("\n")
        current = ""

        for line in lines:
            if len(current) + len(line) + 1 > limit:
                if current:
                    chunks.append(current)
                current = line
            else:
                current += "\n" + line if current else line

        if current:
            chunks.append(current)

        return chunks
