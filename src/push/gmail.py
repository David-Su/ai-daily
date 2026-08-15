"""Gmail SMTP 推送平台"""

import asyncio
import html
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from typing import List

import markdown

from src.config import GmailPushConfig

from .base import PushPlatform

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_TIMEOUT = 30
DEFAULT_SUBJECT = "AI Daily"


class GmailPlatform(PushPlatform):
    """Gmail SMTP 邮件推送"""

    def __init__(self, config: GmailPushConfig):
        super().__init__(config)
        self.username = os.environ.get(config.usernameKeyName, "")
        self.password = os.environ.get(config.passwordKeyName, "")
        self.from_name = config.fromName

    def is_ready(self) -> bool:
        """检查 SMTP 凭据和收件人环境变量是否就绪"""
        if not self.username or not self.password:
            print(
                f"⚠️ Gmail 跳过推送: 未设置 {self.config.usernameKeyName} "
                f"或 {self.config.passwordKeyName} 环境变量"
            )
            return False

        if not self._get_recipients():
            print(f"⚠️ Gmail 跳过推送: 未设置 {self.config.toKeyName} 环境变量")
            return False

        return True

    async def send(self, content: str, title: str = None):
        """异步发送邮件，SMTP 阻塞调用放到线程中执行"""
        await asyncio.to_thread(self._send_sync, content, title)

    def _send_sync(self, content: str, title: str = None):
        """通过 Gmail SMTP（STARTTLS）发送邮件。"""
        message = self._build_message(content, title)

        try:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                smtp.login(self.username, self.password)
                smtp.send_message(message)
        except Exception as e:
            raise RuntimeError(f"Gmail推送失败: {e}") from e

    def _build_message(self, content: str, title: str = None) -> EmailMessage:
        """构建邮件消息"""
        subject = title or DEFAULT_SUBJECT
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = formataddr((self.from_name, self.username))
        message["To"] = ", ".join(self._get_recipients())
        message.set_content(content, subtype="plain", charset="utf-8")
        message.add_alternative(
            self._markdown_to_html(content, subject), subtype="html", charset="utf-8"
        )
        return message

    def _markdown_to_html(self, content: str, subject: str) -> str:
        """将 Markdown 推送内容转成适合邮件显示的 HTML"""
        body = markdown.markdown(
            content,
            extensions=["extra", "sane_lists", "nl2br"],
            output_format="html5",
        )
        safe_subject = html.escape(subject)

        return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{
      margin: 0;
      padding: 24px;
      background: #f6f8fa;
      color: #24292f;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.65;
    }}
    .container {{
      max-width: 760px;
      margin: 0 auto;
      padding: 28px;
      background: #ffffff;
      border: 1px solid #d0d7de;
      border-radius: 8px;
    }}
    h1, h2, h3 {{
      color: #0969da;
      line-height: 1.3;
    }}
    a {{
      color: #0969da;
    }}
    img {{
      max-width: 100%;
      height: auto;
      border-radius: 6px;
    }}
    blockquote {{
      margin: 16px 0;
      padding-left: 14px;
      color: #57606a;
      border-left: 4px solid #d0d7de;
    }}
    code {{
      padding: 2px 5px;
      background: #f6f8fa;
      border-radius: 4px;
    }}
  </style>
</head>
<body>
  <div class="container" aria-label="{safe_subject}">
    {body}
  </div>
</body>
</html>"""

    def _get_recipients(self) -> List[str]:
        """从环境变量读取收件人，支持逗号分隔多个地址。"""
        raw = os.environ.get(self.config.toKeyName, "")
        return [item.strip() for item in raw.split(",") if item.strip()]
