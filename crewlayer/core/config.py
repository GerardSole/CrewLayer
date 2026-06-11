from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ANTHROPIC_API_KEY: str = ""
    DATABASE_URL: str = "postgresql+asyncpg://crewlayer:crewlayer@localhost/crewlayer"
    REDIS_URL: str = "redis://localhost:6379"
    SECRET_KEY: str = "dev-secret-key-change-me"
    EMBEDDING_PROVIDER: str = "anthropic"
    SHORT_MEMORY_TTL: int = 7200
    MAX_MEMORIES_PER_RECALL: int = 10
    LOG_LEVEL: str = "INFO"
    METRICS_TOKEN: str = ""  # empty = only localhost can reach /metrics

    # OpenTelemetry
    OTEL_ENABLED: bool = False
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://localhost:4317"
    OTEL_SERVICE_NAME: str = "crewlayer"


settings = Settings()
