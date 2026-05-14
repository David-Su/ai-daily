"""Gmail SMTP 推送平台"""

import asyncio
import html
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from typing import Dict, List, Optional

import markdown

from .base import PushPlatform


class GmailPlatform(PushPlatform):
    """Gmail SMTP 邮件推送"""

    def __init__(self, config: Dict):
        super().__init__(config)
        self.username_key_name = config.get("usernameKeyName", "GMAIL_USERNAME")
        self.password_key_name = config.get(
            "passwordKeyName", config.get("apiKeyName", "GMAIL_APP_PASSWORD")
        )
        self.to_key_name = config.get("toKeyName", "GMAIL_TO")
        self.username = os.environ.get(self.username_key_name, "")
        self.password = os.environ.get(self.password_key_name, "")
        self.smtp_host = config.get("smtpHost", "smtp.gmail.com")
        self.smtp_port = config.get("smtpPort", 587)
        self.from_name = config.get("fromName", "AI Daily")
        self.timeout = config.get("timeout", 30)

    def validate_config(self, config: Dict) -> bool:
        """检查 Gmail SMTP 配置是否有效"""
        if not config.get("enabled", False):
            return False

        if not self.username or not self.password:
            return False

        if not self._get_recipients():
            return False

        return bool(self.smtp_host and self._get_smtp_port() is not None)

    async def send(self, content: str, title: str = None):
        """异步发送邮件，SMTP 阻塞调用放到线程中执行"""
        await asyncio.to_thread(self._send_sync, content, title)

    def _send_sync(self, content: str, title: str = None):
        """发送到 Gmail SMTP"""
        recipients = self._get_all_recipients()
        message = self._build_message(content, title)
        smtp_port = self._get_smtp_port()

        if smtp_port is None:
            raise RuntimeError("Gmail推送失败: smtpPort 配置无效")

        try:
            if self._use_ssl():
                context = ssl.create_default_context()
                with smtplib.SMTP_SSL(
                    self.smtp_host, smtp_port, timeout=self.timeout, context=context
                ) as smtp:
                    smtp.login(self.username, self.password)
                    smtp.send_message(message, to_addrs=recipients)
            else:
                with smtplib.SMTP(
                    self.smtp_host, smtp_port, timeout=self.timeout
                ) as smtp:
                    if self._use_tls():
                        context = ssl.create_default_context()
                        smtp.starttls(context=context)
                    smtp.login(self.username, self.password)
                    smtp.send_message(message, to_addrs=recipients)
        except Exception as e:
            raise RuntimeError(f"Gmail推送失败: {e}") from e

    def _build_message(self, content: str, title: str = None) -> EmailMessage:
        """构建邮件消息"""
        message = EmailMessage()
        message["Subject"] = title or self.config.get("subject", "AI Daily")
        message["From"] = formataddr((self.from_name, self.username))
        message["To"] = ", ".join(self._get_recipients())

        cc = self._get_addresses("cc")
        if cc:
            message["Cc"] = ", ".join(cc)
        message.set_content(content, subtype="plain", charset="utf-8")
        message.add_alternative(
            self._markdown_to_html(content), subtype="html", charset="utf-8"
        )
        return message

    def _markdown_to_html(self, content: str) -> str:
        """将 Markdown 推送内容转成适合邮件显示的 HTML"""
        body = markdown.markdown(
            content,
            extensions=["extra", "sane_lists", "nl2br"],
            output_format="html5",
        )
        subject = html.escape(self.config.get("subject", "AI Daily"))

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
  <div class="container" aria-label="{subject}">
    {body}
  </div>
</body>
</html>"""

    def _get_all_recipients(self) -> List[str]:
        """获取所有实际投递收件人，包括 cc/bcc"""
        return self._get_recipients() + self._get_addresses("cc") + self._get_addresses(
            "bcc"
        )

    def _get_recipients(self) -> List[str]:
        """获取主收件人，支持配置值或环境变量"""
        recipients = self.config.get("to")
        if not recipients:
            recipients = os.environ.get(self.to_key_name, "")
        return self._normalize_addresses(recipients)

    def _get_addresses(self, key: str) -> List[str]:
        """获取 cc/bcc 地址列表"""
        return self._normalize_addresses(self.config.get(key))

    def _normalize_addresses(self, value) -> List[str]:
        """将字符串或列表形式的邮箱地址转为列表"""
        if not value:
            return []
        if isinstance(value, str):
            candidates = value.split(",")
        elif isinstance(value, list):
            candidates = value
        else:
            return []
        return [
            item.strip()
            for item in candidates
            if isinstance(item, str) and item.strip()
        ]

    def _get_smtp_port(self) -> Optional[int]:
        """读取 SMTP 端口"""
        try:
            return int(self.smtp_port)
        except (TypeError, ValueError):
            return None

    def _use_tls(self) -> bool:
        """是否启用 STARTTLS"""
        return self.config.get("useTLS", self.config.get("useTls", True))

    def _use_ssl(self) -> bool:
        """是否使用 SMTP SSL 连接"""
        return self.config.get("useSSL", self.config.get("useSsl", False))
