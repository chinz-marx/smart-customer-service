from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


# backend 目录路径，用来定位 .env。Path 写法可以同时兼容 Windows 和 Linux。
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """应用运行配置。

    真实的模型参数放在 backend/.env 中；这里负责声明字段、默认值和读取方式。
    这样可以避免把 API Key 写进代码仓库。
    """

    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", env_file_encoding="utf-8")

    app_name: str = "smart-customer-service-api"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    doubao_api_key: str = "YOUR_DOUBAO_API_KEY"
    doubao_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    doubao_model: str = "doubao-seed-1-6-250615"
    doubao_temperature: float = 0.3

    @property
    def cors_origin_list(self) -> list[str]:
        """把逗号分隔的 CORS 配置转成 FastAPI 需要的列表。"""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def has_real_api_key(self) -> bool:
        """判断是否配置了真实模型 Key。

        没有真实 Key 时，系统走 local-fallback，方便前端和流程先联调。
        """
        key = self.doubao_api_key.strip()
        return bool(key) and not key.startswith("YOUR_")


@lru_cache
def get_settings() -> Settings:
    """缓存配置对象，避免每次请求都重新读取 .env。"""
    return Settings()