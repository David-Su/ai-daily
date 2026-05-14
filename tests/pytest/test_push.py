"""推送模块测试"""

import os
import pytest
import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from push.discord import DiscordPlatform
from push.feishu import FeishuPlatform
from push.gmail import GmailPlatform
from push import create_platform


class TestDiscordPlatform:
    """测试Discord推送"""

    def test_validate_config_valid(self):
        config = {
            "enabled": True,
            "apiKeyName": "DISCORD_WEBHOOK_URL",
        }
        with patch.dict(
            os.environ,
            {"DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/123456/abcdef"},
        ):
            platform = DiscordPlatform(config)
            assert platform.validate_config(config) is True

    def test_validate_config_disabled(self):
        config = {
            "enabled": False,
            "apiKeyName": "DISCORD_WEBHOOK_URL",
        }
        with patch.dict(
            os.environ,
            {"DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/123456/abcdef"},
        ):
            platform = DiscordPlatform(config)
            assert platform.validate_config(config) is False

    def test_validate_config_missing_webhook(self):
        config = {"enabled": True, "apiKeyName": "DISCORD_WEBHOOK_URL"}
        with patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": ""}):
            platform = DiscordPlatform(config)
            assert platform.validate_config(config) is False

    def test_validate_config_invalid_url(self):
        config = {"enabled": True, "apiKeyName": "DISCORD_WEBHOOK_URL"}
        with patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": "not-a-valid-url"}):
            platform = DiscordPlatform(config)
            assert platform.validate_config(config) is False

    def test_validate_config_wrong_domain(self):
        config = {"enabled": True, "apiKeyName": "DISCORD_WEBHOOK_URL"}
        with patch.dict(
            os.environ, {"DISCORD_WEBHOOK_URL": "https://example.com/webhook"}
        ):
            platform = DiscordPlatform(config)
            assert platform.validate_config(config) is False

    def test_split_content_short(self):
        with patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": "https://test.com"}):
            config = {"apiKeyName": "DISCORD_WEBHOOK_URL"}
            platform = DiscordPlatform(config)
            short_content = "Hello"
            chunks = platform._split_content(short_content, limit=2000)
            assert len(chunks) == 1
            assert chunks[0] == "Hello"

    def test_split_content_long_message(self):
        with patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": "https://test.com"}):
            config = {"apiKeyName": "DISCORD_WEBHOOK_URL"}
            platform = DiscordPlatform(config)
            long_content = "A\n" * 2500
            chunks = platform._split_content(long_content, limit=2000)
            assert len(chunks) > 1
            assert all(len(c) <= 2000 for c in chunks)

    def test_split_content_exact_boundary(self):
        with patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": "https://test.com"}):
            config = {"apiKeyName": "DISCORD_WEBHOOK_URL"}
            platform = DiscordPlatform(config)
            content = "A" * 2000
            chunks = platform._split_content(content, limit=2000)
            assert len(chunks) == 1

    def test_split_content_unicode(self):
        with patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": "https://test.com"}):
            config = {"apiKeyName": "DISCORD_WEBHOOK_URL"}
            platform = DiscordPlatform(config)
            content = "你好" * 500
            chunks = platform._split_content(content, limit=100)
            assert len(chunks) >= 1

    @pytest.mark.asyncio
    async def test_send_success(self):
        with patch.dict(
            os.environ,
            {"DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/test/abc"},
        ):
            config = {"apiKeyName": "DISCORD_WEBHOOK_URL"}
            platform = DiscordPlatform(config)

            with patch.object(platform, "send", new_callable=AsyncMock) as mock_send:
                mock_send.return_value = True

                result = await mock_send("Test message")

            assert result is True

    @pytest.mark.asyncio
    async def test_send_failure(self):
        with patch.dict(
            os.environ,
            {"DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/test/abc"},
        ):
            config = {"apiKeyName": "DISCORD_WEBHOOK_URL"}
            platform = DiscordPlatform(config)

            with patch.object(platform, "send", new_callable=AsyncMock) as mock_send:
                mock_send.return_value = False

                result = await mock_send("Test message")

            assert result is False


class TestFeishuPlatform:
    """测试飞书推送"""

    def test_validate_config_valid(self):
        config = {
            "enabled": True,
            "apiKeyName": "FEISHU_WEBHOOK_URL",
        }
        with patch.dict(os.environ, {"FEISHU_WEBHOOK_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/test"}):
            platform = FeishuPlatform(config)
            assert platform.validate_config(config) is True

    def test_validate_config_disabled(self):
        config = {
            "enabled": False,
            "apiKeyName": "FEISHU_WEBHOOK_URL",
        }
        with patch.dict(os.environ, {"FEISHU_WEBHOOK_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/test"}):
            platform = FeishuPlatform(config)
            assert platform.validate_config(config) is False

    def test_validate_config_missing_key(self):
        config = {"enabled": True, "apiKeyName": "FEISHU_WEBHOOK_URL"}
        with patch.dict(os.environ, {"FEISHU_WEBHOOK_URL": ""}):
            platform = FeishuPlatform(config)
            assert platform.validate_config(config) is False

    def test_validate_config_any_non_empty_webhook(self):
        config = {"enabled": True, "apiKeyName": "FEISHU_WEBHOOK_URL"}
        with patch.dict(os.environ, {"FEISHU_WEBHOOK_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/test"}):
            platform = FeishuPlatform(config)
            assert platform.validate_config(config) is True


class TestGmailPlatform:
    """测试 Gmail 推送"""

    def test_validate_config_valid(self):
        config = {
            "enabled": True,
            "usernameKeyName": "GMAIL_USERNAME",
            "passwordKeyName": "GMAIL_APP_PASSWORD",
            "to": ["receiver@example.com"],
        }
        with patch.dict(
            os.environ,
            {
                "GMAIL_USERNAME": "sender@gmail.com",
                "GMAIL_APP_PASSWORD": "app-password",
            },
        ):
            platform = GmailPlatform(config)
            assert platform.validate_config(config) is True

    def test_validate_config_disabled(self):
        config = {
            "enabled": False,
            "usernameKeyName": "GMAIL_USERNAME",
            "passwordKeyName": "GMAIL_APP_PASSWORD",
            "to": ["receiver@example.com"],
        }
        with patch.dict(
            os.environ,
            {
                "GMAIL_USERNAME": "sender@gmail.com",
                "GMAIL_APP_PASSWORD": "app-password",
            },
        ):
            platform = GmailPlatform(config)
            assert platform.validate_config(config) is False

    def test_validate_config_missing_credentials(self):
        config = {
            "enabled": True,
            "usernameKeyName": "GMAIL_USERNAME",
            "passwordKeyName": "GMAIL_APP_PASSWORD",
            "to": ["receiver@example.com"],
        }
        with patch.dict(
            os.environ,
            {"GMAIL_USERNAME": "", "GMAIL_APP_PASSWORD": ""},
        ):
            platform = GmailPlatform(config)
            assert platform.validate_config(config) is False

    def test_validate_config_to_from_env(self):
        config = {
            "enabled": True,
            "usernameKeyName": "GMAIL_USERNAME",
            "passwordKeyName": "GMAIL_APP_PASSWORD",
            "toKeyName": "GMAIL_TO",
        }
        with patch.dict(
            os.environ,
            {
                "GMAIL_USERNAME": "sender@gmail.com",
                "GMAIL_APP_PASSWORD": "app-password",
                "GMAIL_TO": "one@example.com,two@example.com",
            },
        ):
            platform = GmailPlatform(config)
            assert platform.validate_config(config) is True
            assert platform._get_recipients() == [
                "one@example.com",
                "two@example.com",
            ]

    def test_validate_config_invalid_smtp_port(self):
        config = {
            "enabled": True,
            "usernameKeyName": "GMAIL_USERNAME",
            "passwordKeyName": "GMAIL_APP_PASSWORD",
            "to": ["receiver@example.com"],
            "smtpPort": "invalid",
        }
        with patch.dict(
            os.environ,
            {
                "GMAIL_USERNAME": "sender@gmail.com",
                "GMAIL_APP_PASSWORD": "app-password",
            },
        ):
            platform = GmailPlatform(config)
            assert platform.validate_config(config) is False

    def test_build_message(self):
        config = {
            "enabled": True,
            "usernameKeyName": "GMAIL_USERNAME",
            "passwordKeyName": "GMAIL_APP_PASSWORD",
            "to": "receiver@example.com",
            "cc": ["copy@example.com"],
            "fromName": "AI Daily Bot",
        }
        with patch.dict(
            os.environ,
            {
                "GMAIL_USERNAME": "sender@gmail.com",
                "GMAIL_APP_PASSWORD": "app-password",
            },
        ):
            platform = GmailPlatform(config)
            message = platform._build_message("**Hello**", "Daily News")

        assert message["Subject"] == "Daily News"
        assert message["From"] == "AI Daily Bot <sender@gmail.com>"
        assert message["To"] == "receiver@example.com"
        assert message["Cc"] == "copy@example.com"
        assert message.get_body(("plain",)).get_content().strip() == "**Hello**"

        html_body = message.get_body(("html",)).get_content()
        assert "<strong>Hello</strong>" in html_body
        assert "AI Daily Bot" not in html_body

    def test_send_sync_success(self):
        config = {
            "enabled": True,
            "usernameKeyName": "GMAIL_USERNAME",
            "passwordKeyName": "GMAIL_APP_PASSWORD",
            "to": ["receiver@example.com"],
        }
        with patch.dict(
            os.environ,
            {
                "GMAIL_USERNAME": "sender@gmail.com",
                "GMAIL_APP_PASSWORD": "app-password",
            },
        ), patch("push.gmail.smtplib.SMTP") as mock_smtp:
            smtp = mock_smtp.return_value.__enter__.return_value
            platform = GmailPlatform(config)
            platform._send_sync("Hello", "Daily News")

        mock_smtp.assert_called_once_with("smtp.gmail.com", 587, timeout=30)
        smtp.starttls.assert_called_once()
        smtp.login.assert_called_once_with("sender@gmail.com", "app-password")
        smtp.send_message.assert_called_once()
        message = smtp.send_message.call_args.args[0]
        assert message["Subject"] == "Daily News"
        assert message.get_body(("html",)) is not None
        assert smtp.send_message.call_args.kwargs["to_addrs"] == [
            "receiver@example.com"
        ]


class TestPushFactory:
    """测试平台工厂"""

    def test_create_enabled_platform(self):
        config = {
            "enabled": True,
            "apiKeyName": "DISCORD_WEBHOOK_URL",
        }
        with patch.dict(
            os.environ,
            {"DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/123/abc"},
        ):
            platform = create_platform("discord", config)
            assert platform is not None

    def test_create_disabled_platform_returns_none(self):
        config = {"enabled": False, "apiKeyName": "DISCORD_WEBHOOK_URL"}
        platform = create_platform("discord", config)
        assert platform is None

    def test_create_unknown_platform_raises(self):
        with pytest.raises(ValueError):
            create_platform("unknown", {})

    def test_create_feishu_platform(self):
        config = {
            "enabled": True,
            "apiKeyName": "FEISHU_WEBHOOK_URL",
        }
        with patch.dict(os.environ, {"FEISHU_WEBHOOK_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/test"}):
            platform = create_platform("feishu", config)
            assert platform is not None
            assert isinstance(platform, FeishuPlatform)

    def test_create_discord_platform(self):
        config = {
            "enabled": True,
            "apiKeyName": "DISCORD_WEBHOOK_URL",
        }
        with patch.dict(
            os.environ,
            {"DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/test/abc"},
        ):
            platform = create_platform("discord", config)
            assert platform is not None
            assert isinstance(platform, DiscordPlatform)

    def test_create_gmail_platform(self):
        config = {
            "enabled": True,
            "usernameKeyName": "GMAIL_USERNAME",
            "passwordKeyName": "GMAIL_APP_PASSWORD",
            "to": ["receiver@example.com"],
        }
        with patch.dict(
            os.environ,
            {
                "GMAIL_USERNAME": "sender@gmail.com",
                "GMAIL_APP_PASSWORD": "app-password",
            },
        ):
            platform = create_platform("gmail", config)
            assert platform is not None
            assert isinstance(platform, GmailPlatform)
