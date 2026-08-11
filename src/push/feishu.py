"""飞书推送平台"""

import os
from typing import Dict

import aiohttp

from src.config import WebhookPushConfig

from .base import PushPlatform


class FeishuPlatform(PushPlatform):
    """飞书 Webhook 推送"""

    def __init__(self, config: WebhookPushConfig):
        super().__init__(config)
        self.webhook_url = os.environ.get(config.apiKeyName, "")

    def is_ready(self) -> bool:
        """检查 Webhook 环境变量是否已设置"""
        if not self.webhook_url:
            print(f"⚠️ 飞书 跳过推送: 未设置 {self.config.apiKeyName} 环境变量")
            return False
        return True

    async def send(self, content: str, title: str = None):
        """发送到飞书"""
        chunks = self._split_content(content, limit=8000)

        async with aiohttp.ClientSession() as session:
            for chunk in chunks:
                payload = self._build_payload(chunk, title)
                async with session.post(self.webhook_url, json=payload) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        raise RuntimeError(f"飞书推送失败: {resp.status} - {text}")
                    data = await resp.json()
                    if data.get("code") != 0:
                        raise RuntimeError(f"飞书推送失败: {data.get('msg')}")

    def _build_payload(self, content: str, title: str = None) -> Dict:
        """
        构建飞书卡片消息 payload，支持 Markdown，
        参考  https://open.feishu.cn/document/feishu-cards/card-json-v2-structure
        """

        header = {}
        if title:
            header = {
                "title": {"content": title, "tag": "plain_text"},
                "template": "blue",
            }

        return {
            "msg_type": "interactive",
            "card": {
                "schema": "2.0",  # 【重点1】显式声明使用 V2 版本结构
                "header": header,
                "body": {  # 【重点2】V2 中，所有的内容元素都必须放在 body 里面
                    "elements": [
                        {
                            "tag": "markdown",
                            "content": content,
                            "text_align": "left",  # 可选：left / center / right
                        },
                    ],
                },
            },
        }

    def _split_content(self, content: str, limit: int = 8000) -> list:
        """飞书卡片消息 markdown 元素限制 8000 字符"""
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
