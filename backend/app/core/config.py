import json
from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND_DIR / ".env", PROJECT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "SalesPilot CRM"
    APP_ENV: str = "development"

    DATABASE_URL: str
    DATABASE_SYNC_URL: str

    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480

    OPENAI_API_KEY: str | None = None
    OPENAI_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    OPENAI_MODEL: str = "qwen-plus"

    DASHSCOPE_API_KEY: str | None = None
    DASHSCOPE_BASE_URL: str = "https://dashscope.aliyuncs.com"
    PARAFORMER_MODEL: str = "paraformer-v2"
    PARAFORMER_LANGUAGE_HINTS: str = '["zh", "en"]'

    XFYUN_REALTIME_APP_ID: str ="pc20onli"
    XFYUN_REALTIME_API_KEY: str = "d9f4aa7ea6d94faca62cd88a28fd5234"
    XFYUN_REALTIME_TOKEN: str = "10003"
    XFYUN_REALTIME_WS_URL: str = "wss://multirobot-test.kxjlcc.com"
    XFYUN_REALTIME_PUNC: str = "1"
    XFYUN_REALTIME_ENG_LANG_TYPE: str = "1"

    REDIS_URL: str = "redis://localhost:6379/0"

    # 管理员默认密码，生产环境请务必在 .env 中设置强密码
    ADMIN_DEFAULT_PASSWORD: str = "Admin@2024#CRM"

    # 密码强度：最短长度
    PASSWORD_MIN_LENGTH: int = 8

    CORS_ORIGINS: str = (
        '["http://localhost:3000","http://127.0.0.1:3000",'
        '"http://localhost:5173","http://127.0.0.1:5173",'
        '"http://localhost:5500","http://127.0.0.1:5500",'
        '"http://localhost:5501","http://127.0.0.1:5501",'
        '"http://localhost:8080","http://127.0.0.1:8080"]'
    )

    @property
    def cors_origins_list(self) -> List[str]:
        return json.loads(self.CORS_ORIGINS)

    @property
    def paraformer_language_hints_list(self) -> List[str]:
        return json.loads(self.PARAFORMER_LANGUAGE_HINTS)


settings = Settings()
