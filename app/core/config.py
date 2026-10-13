"""Runtime settings."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.exceptions import AppError


class Settings(BaseSettings):
    """Environment-backed application settings."""

    database_url: str = "sqlite:///./data/healthevidence.db"
    llm_provider: str = "ollama"
    environment: str = "local"
    log_level: str = "INFO"
    seed_on_startup: bool = True
    cors_origins: str = "http://localhost:5173,http://localhost:3000"
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    gemini_api_key: str = ""
    redis_url: str = ""
    langfuse_host: str = ""
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    # Legacy shared override. Prefer GEMINI_MODEL_NAME / OLLAMA_MODEL_NAME.
    model_name: str = ""
    gemini_model_name: str = "gemini-3.1-flash-lite"
    ollama_model_name: str = "medgemma:4b"
    openai_model_name: str = "gpt-4o-mini"
    anthropic_model_name: str = "claude-3-5-haiku-latest"
    embedding_model: str = "dense-hash-v1"
    # dense-hash (local) | openai — openai requires OPENAI_API_KEY + embedding_model.
    embedding_backend: str = "dense-hash"
    embedding_dim: int = 256
    # When on (auto for staging/prod), assigned cases are restricted to assignee + seniors/admin.
    enforce_need_to_know: bool | None = None
    ollama_base_url: str = "http://127.0.0.1:11434"
    openai_base_url: str = "https://api.openai.com/v1"
    anthropic_base_url: str = "https://api.anthropic.com"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    enable_tracing: bool = True
    llm_timeout_seconds: float = 120.0
    llm_fallback_providers: str = "local"
    a2a_enabled: bool = True
    imaging_backend: str = "monai"
    # ai_primary = LLM clinical intelligence first; rules = deterministic only
    criteria_eval_mode: str = "ai_primary"
    # Gap visit-note coaching drafts via LLM (unset → follow criteria_eval_mode).
    ai_gap_drafts: bool | None = None
    auth_mode: str = "dev-jwt"
    oidc_issuer: str = ""
    oidc_audience: str = "healthevidence-api"
    oidc_jwks_url: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_roles_claim: str = "roles"
    oidc_required_roles: str = "patient,senior_clinician,resident,staff,admin,reviewer"
    default_locale: str = "en"
    supported_locales: str = "en,es,fr,de,pt,hi,ar,zh,ja"
    data_residency_region: str = "global"
    # PHI / multi-org: default off — synthetic/consent packets only until attested program.
    allow_phi: bool = False
    phi_program_attested: bool = False
    # External LLM egress with PHI requires vendor BAA + explicit residency attestation.
    llm_baa_attested: bool = False
    llm_phi_egress_allowed: bool = False
    # Invented lifelong biography — never when PHI is on; local/test demo only by default.
    synthetic_lifelong: bool | None = None
    # HS256 secret for AUTH_MODE=dev-jwt (required outside unit tests).
    dev_jwt_secret: str = ""
    default_org_code: str = "ORG-000001"
    default_org_name: str = "Krishna Multispecialty Hospital, Pune"
    # When true, care-team tokens must carry org_id/org_code and only see that org's charts.
    # Admin bypasses. Unset → auto-on for pilot/staging/production; off for local/test.
    # Set ENFORCE_ORG_SCOPE explicitly to override.
    enforce_org_scope: bool | None = None
    # Hospital interface simulator (POST /hospital/pipeline/simulate).
    # Unset → allowed only on local/test/pilot practice desks; off in shared live.
    hospital_allow_simulate: bool | None = None
    # Shared secret for HIS/FHIR machine clients (header X-Hospital-Api-Key).
    hospital_interface_api_key: str = ""
    # Desk SLA for open evidence packs (minutes). Breach flags Today / ops metrics.
    packet_sla_minutes: int = 240

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def env_name(self) -> str:
        return self.environment.strip().lower()

    def is_shared_live_env(self) -> bool:
        """Staging / production / kubernetes — full live gates (OIDC, Postgres, no seed)."""
        return self.env_name() in {"staging", "production", "prod", "kubernetes"}

    def hospital_practice_mode(self) -> bool:
        """True until PHI program is attested — synthetic/consent feeds only."""
        return not (self.allow_phi and self.phi_program_attested)

    def hospital_simulate_allowed(self) -> bool:
        if self.hospital_allow_simulate is not None:
            return bool(self.hospital_allow_simulate)
        if not self.hospital_practice_mode():
            return False
        return self.env_name() in {"local", "test", "pilot"}

    def org_scope_enforced(self) -> bool:
        """Tenant isolation: on by default outside local/test UAT."""
        if self.enforce_org_scope is not None:
            return bool(self.enforce_org_scope)
        return self.env_name() not in {"local", "test"}

    def meta_public(self) -> bool:
        """Unauthenticated GET /meta* only on laptop UAT."""
        return self.env_name() in {"local", "test"}

    def alembic_required(self) -> bool:
        """Fail closed on migration errors for shared Postgres live desks."""
        if "sqlite" in self.database_url.lower():
            return False
        return self.is_shared_live_env() or self.env_name() == "pilot"

    def pilot_postgres_harness(self) -> bool:
        """CI/local Postgres pilot gate with mintable tokens — not a shared tenant."""
        import os

        if self.env_name() != "pilot":
            return False
        flag = (os.environ.get("PILOT_POSTGRES_TEST") or "").strip().lower()
        return flag in {"1", "true", "yes", "on"}

    def dev_token_allowed(self) -> bool:
        """Dev JWT minting only for laptop/local UAT — never shared live or real pilot."""
        mode = self.auth_mode.strip().lower()
        env = self.env_name()
        if mode not in {"dev-jwt", "none"}:
            return False
        if self.is_shared_live_env():
            return False
        if env == "pilot":
            # Automated Postgres harness only (PILOT_POSTGRES_TEST=1).
            return self.pilot_postgres_harness()
        return env in {"local", "test"}

    def synthetic_lifelong_enabled(self) -> bool:
        """Invented cross-facility biography is demo-only and never mixes with PHI."""
        if self.allow_phi:
            return False
        if self.synthetic_lifelong is not None:
            return bool(self.synthetic_lifelong)
        return self.env_name() in {"local", "test"}

    def external_llm_phi_blocked(self) -> bool:
        """True when cloud LLM providers must not see chart text under PHI."""
        if not self.allow_phi:
            return False
        if self.llm_baa_attested and self.llm_phi_egress_allowed:
            return False
        return True

    def require_dev_jwt_secret(self) -> str:
        """HMAC for dev-jwt — never a hard-coded production-shared secret."""
        secret = (self.dev_jwt_secret or self.oidc_client_secret or "").strip()
        if not secret and (
            self.env_name() == "test" or self.pilot_postgres_harness()
        ):
            return "test-only-healthevidence-hmac-do-not-reuse"
        if len(secret) < 32:
            raise AppError(
                "AUTH_DEV_SECRET_REQUIRED",
                "DEV_JWT_SECRET (or OIDC_CLIENT_SECRET) must be set and at least 32 characters "
                "for AUTH_MODE=dev-jwt. There is no default signing key.",
                503,
            )
        return secret

    def docs_exposed(self) -> bool:
        """Interactive OpenAPI UI only on local/test desks."""
        return self.env_name() in {"local", "test"}

    def need_to_know_enforced(self) -> bool:
        if self.enforce_need_to_know is not None:
            return bool(self.enforce_need_to_know)
        return self.is_shared_live_env()

    def use_openai_embeddings(self) -> bool:
        backend = self.embedding_backend.strip().lower()
        if backend in {"openai", "openai-embeddings"}:
            return True
        return self.embedding_model.strip().lower().startswith("openai")

    def origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    def locale_list(self) -> list[str]:
        return [item.strip() for item in self.supported_locales.split(",") if item.strip()]

    def llm_provider_chain(self) -> list[str]:
        primary = self.llm_provider.strip().lower()
        chain = [primary] if primary else []
        for item in self.llm_fallback_providers.split(","):
            name = item.strip().lower()
            if name and name not in chain:
                chain.append(name)
        return chain

    def model_for_provider(self, provider: str | None = None) -> str:
        """Resolve the chat model for a provider. Keeps Gemini and Ollama names separate."""
        name = (provider or self.llm_provider).strip().lower()
        legacy = self.model_name.strip()
        if name == "gemini":
            # Ignore legacy Ollama tags left in MODEL_NAME when using Gemini.
            if legacy and not _looks_like_ollama_tag(legacy):
                return legacy.removeprefix("models/")
            return (self.gemini_model_name.strip() or "gemini-3.1-flash-lite").removeprefix(
                "models/"
            )
        if name == "ollama":
            if legacy and _looks_like_ollama_tag(legacy):
                return legacy
            return self.ollama_model_name.strip() or "medgemma:4b"
        if name == "openai":
            return legacy or self.openai_model_name.strip() or "gpt-4o-mini"
        if name == "anthropic":
            return legacy or self.anthropic_model_name.strip() or "claude-3-5-haiku-latest"
        if name == "local":
            return "local-grounded"
        return legacy or self.ollama_model_name.strip() or "medgemma:4b"

    def validate_live_configuration(self) -> None:
        provider = self.llm_provider.strip().lower()
        if provider not in {"openai", "anthropic", "ollama", "gemini", "local"}:
            raise AppError(
                "LIVE_CONFIG_INVALID",
                "LLM_PROVIDER must be openai, anthropic, ollama, gemini, or local; "
                f"got {self.llm_provider!r}.",
                503,
            )
        if self.imaging_backend.strip().lower() not in {"monai", "monai-isolated"}:
            raise AppError(
                "LIVE_CONFIG_INVALID",
                "IMAGING_BACKEND must be monai.",
                503,
            )
        env = self.env_name()
        auth = self.auth_mode.strip().lower()
        if env not in {"test"} and auth in {"", "none", "off", "disabled"}:
            raise AppError(
                "LIVE_CONFIG_INVALID",
                "AUTH_MODE=none is not allowed outside tests. Use dev-jwt or oidc.",
                503,
            )
        if env == "pilot":
            if "sqlite" in self.database_url.lower():
                raise AppError(
                    "LIVE_CONFIG_INVALID",
                    "SQLite is not allowed in pilot; use PostgreSQL.",
                    503,
                )
            harness = self.pilot_postgres_harness()
            if auth != "oidc" and not (harness and auth == "dev-jwt"):
                raise AppError(
                    "LIVE_CONFIG_INVALID",
                    "AUTH_MODE=oidc is required in pilot (dev-jwt minting is disabled).",
                    503,
                )
            if auth == "oidc" and (
                not self.oidc_issuer.strip() or not self.oidc_jwks_url.strip()
            ):
                raise AppError(
                    "LIVE_CONFIG_INVALID",
                    "OIDC_ISSUER and OIDC_JWKS_URL are required when AUTH_MODE=oidc.",
                    503,
                )
            if self.allow_phi and not self.phi_program_attested:
                raise AppError(
                    "LIVE_CONFIG_INVALID",
                    "ALLOW_PHI requires PHI_PROGRAM_ATTESTED=true under an accountable "
                    "privacy/clinical program. Default remains synthetic-only.",
                    503,
                )
            if self.external_llm_phi_blocked() and any(
                name in {"openai", "anthropic", "gemini"} for name in self.llm_provider_chain()
            ):
                raise AppError(
                    "LIVE_CONFIG_INVALID",
                    "ALLOW_PHI with openai/anthropic/gemini requires LLM_BAA_ATTESTED and "
                    "LLM_PHI_EGRESS_ALLOWED (or use LLM_PROVIDER=local/ollama).",
                    503,
                )

        if self.is_shared_live_env():
            if auth != "oidc":
                raise AppError(
                    "LIVE_CONFIG_INVALID",
                    "AUTH_MODE=oidc is required in staging, production, and kubernetes.",
                    503,
                )
            if not self.oidc_issuer.strip() or not self.oidc_jwks_url.strip():
                raise AppError(
                    "LIVE_CONFIG_INVALID",
                    "OIDC_ISSUER and OIDC_JWKS_URL are required in shared live environments.",
                    503,
                )
            if provider == "openai" and not self.openai_api_key.strip():
                raise AppError("LIVE_CONFIG_INVALID", "OPENAI_API_KEY is required.", 503)
            if provider == "anthropic" and not self.anthropic_api_key.strip():
                raise AppError("LIVE_CONFIG_INVALID", "ANTHROPIC_API_KEY is required.", 503)
            if provider == "gemini" and not self.gemini_api_key.strip():
                raise AppError("LIVE_CONFIG_INVALID", "GEMINI_API_KEY is required.", 503)
            if "sqlite" in self.database_url.lower():
                raise AppError(
                    "LIVE_CONFIG_INVALID",
                    "SQLite is not allowed in shared live environments; use PostgreSQL.",
                    503,
                )
            if self.seed_on_startup:
                raise AppError(
                    "LIVE_CONFIG_INVALID",
                    "SEED_ON_STARTUP must be false in staging, production, and kubernetes. "
                    "Load reference data through controlled migration / import only.",
                    503,
                )
            if not self.org_scope_enforced():
                raise AppError(
                    "LIVE_CONFIG_INVALID",
                    "ENFORCE_ORG_SCOPE must be enabled (or unset for auto-on) in shared live.",
                    503,
                )
            if self.allow_phi and not self.phi_program_attested:
                raise AppError(
                    "LIVE_CONFIG_INVALID",
                    "ALLOW_PHI requires PHI_PROGRAM_ATTESTED=true under an accountable "
                    "privacy/clinical program. Default remains synthetic-only.",
                    503,
                )
            if not self.hospital_practice_mode() and self.hospital_simulate_allowed():
                raise AppError(
                    "LIVE_CONFIG_INVALID",
                    "Hospital simulator cannot stay enabled when PHI live feeds are attested. "
                    "Set HOSPITAL_ALLOW_SIMULATE=false.",
                    503,
                )
            if self.external_llm_phi_blocked() and any(
                name in {"openai", "anthropic", "gemini"} for name in self.llm_provider_chain()
            ):
                raise AppError(
                    "LIVE_CONFIG_INVALID",
                    "ALLOW_PHI with openai/anthropic/gemini requires LLM_BAA_ATTESTED and "
                    "LLM_PHI_EGRESS_ALLOWED (or use LLM_PROVIDER=local/ollama).",
                    503,
                )


def _looks_like_ollama_tag(value: str) -> bool:
    lowered = value.strip().lower()
    if not lowered or lowered.startswith("local"):
        return False
    if lowered.startswith("gemini") or lowered.startswith("gpt-") or lowered.startswith("claude"):
        return False
    # Ollama tags: medgemma:4b, llama3.2, mistral, etc.
    return ":" in lowered or lowered in {
        "llama3",
        "llama3.2",
        "llama3.1",
        "mistral",
        "phi3",
        "qwen2",
        "medgemma",
        "meditron",
        "medllama2",
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()
