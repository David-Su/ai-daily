"""推送平台基类"""
from abc import ABC, abstractmethod

from src.config import ConfigModel


class PushPlatform(ABC):
    """推送平台抽象基类"""

    def __init__(self, config: ConfigModel):
        self.config = config

    @abstractmethod
    def is_ready(self) -> bool:
        """检查运行所需的环境变量是否就绪"""
        pass

    @abstractmethod
    async def send(self, content: str, title: str = None):
        """发送内容"""
        pass
