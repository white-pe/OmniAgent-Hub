"""Provider persistence and credential orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from pawteam_api.models import Agent, Provider, ProviderModel
from pawteam_api.provider_schemas import (
    ProviderCreate,
    ProviderResponse,
    ProviderUpdate,
)
from pawteam_api.security.secret_store import SecretStore


class ProviderNotFoundError(LookupError):
    pass


class ProviderConflictError(ValueError):
    pass


class ProviderModelNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class RuntimeProvider:
    provider_id: str
    provider_name: str
    base_url: str
    api_key: str
    model_id: str
    model_name: str


class ProviderService:
    def __init__(self, session: AsyncSession, secret_store: SecretStore) -> None:
        self.session = session
        self.secret_store = secret_store

    async def list(self) -> list[ProviderResponse]:
        result = await self.session.scalars(
            select(Provider)
            .options(selectinload(Provider.models))
            .order_by(Provider.created_at, Provider.name)
        )
        return [self._response(provider) for provider in result.unique().all()]

    async def get(self, provider_id: str) -> ProviderResponse:
        return self._response(await self._entity(provider_id))

    async def create(self, payload: ProviderCreate) -> ProviderResponse:
        provider_id = str(uuid4())
        secret_reference = f"provider-{provider_id}"
        provider = Provider(
            id=provider_id,
            name=payload.name,
            kind=payload.kind,
            base_url=payload.base_url,
            api_key_ref=secret_reference,
            enabled=payload.enabled,
            models=[
                ProviderModel(
                    model_name=model.model_name,
                    display_name=model.display_name or model.model_name,
                    capabilities_json=model.capabilities,
                    enabled=model.enabled,
                )
                for model in payload.models
            ],
        )
        self.secret_store.set(secret_reference, payload.api_key.get_secret_value())
        self.session.add(provider)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            self.secret_store.delete(secret_reference)
            raise ProviderConflictError("Provider name already exists") from exc
        except Exception:
            await self.session.rollback()
            self.secret_store.delete(secret_reference)
            raise
        return await self.get(provider_id)

    async def update(
        self, provider_id: str, payload: ProviderUpdate
    ) -> ProviderResponse:
        provider = await self._entity(provider_id)
        changes = payload.model_fields_set
        previous_secret: str | None = None
        if "name" in changes and payload.name is not None:
            provider.name = payload.name
        if "base_url" in changes and payload.base_url is not None:
            provider.base_url = payload.base_url
        if "enabled" in changes and payload.enabled is not None:
            provider.enabled = payload.enabled
        if "models" in changes and payload.models is not None:
            existing_models = {model.model_name: model for model in provider.models}
            next_models: list[ProviderModel] = []
            for model_input in payload.models:
                model = existing_models.pop(model_input.model_name, None)
                if model is None:
                    model = ProviderModel(model_name=model_input.model_name)
                model.display_name = model_input.display_name or model_input.model_name
                model.capabilities_json = model_input.capabilities
                model.enabled = model_input.enabled
                next_models.append(model)
            removed_ids = [model.id for model in existing_models.values()]
            if removed_ids:
                agent_using_model = await self.session.scalar(
                    select(Agent.id).where(Agent.model_id.in_(removed_ids)).limit(1)
                )
                if agent_using_model is not None:
                    raise ProviderConflictError(
                        "Cannot remove a Model that is used by an Agent"
                    )
            for removed_model in existing_models.values():
                await self.session.delete(removed_model)
            provider.models = next_models
        if "api_key" in changes and payload.api_key is not None:
            previous_secret = self.secret_store.get(provider.api_key_ref)
            self.secret_store.set(
                provider.api_key_ref, payload.api_key.get_secret_value()
            )
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            if previous_secret is not None:
                self.secret_store.set(provider.api_key_ref, previous_secret)
            raise ProviderConflictError("Provider name already exists") from exc
        except Exception:
            await self.session.rollback()
            if previous_secret is not None:
                self.secret_store.set(provider.api_key_ref, previous_secret)
            raise
        return await self.get(provider_id)

    async def delete(self, provider_id: str) -> None:
        provider = await self._entity(provider_id)
        secret_reference = provider.api_key_ref
        await self.session.delete(provider)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ProviderConflictError(
                "Provider is used by an Agent and cannot be deleted"
            ) from exc
        self.secret_store.delete(secret_reference)

    async def runtime(
        self, provider_id: str, model_id: str | None = None
    ) -> RuntimeProvider:
        provider = await self._entity(provider_id)
        if not provider.enabled:
            raise ProviderConflictError("Provider is disabled")
        candidates = [model for model in provider.models if model.enabled]
        if model_id is None:
            model = candidates[0] if candidates else None
        else:
            model = next((item for item in candidates if item.id == model_id), None)
        if model is None:
            raise ProviderModelNotFoundError("Enabled model not found")
        return RuntimeProvider(
            provider_id=provider.id,
            provider_name=provider.name,
            base_url=provider.base_url,
            api_key=self.secret_store.get(provider.api_key_ref),
            model_id=model.id,
            model_name=model.model_name,
        )

    async def _entity(self, provider_id: str) -> Provider:
        provider = await self.session.scalar(
            select(Provider)
            .where(Provider.id == provider_id)
            .options(selectinload(Provider.models))
        )
        if provider is None:
            raise ProviderNotFoundError(provider_id)
        return provider

    def _response(self, provider: Provider) -> ProviderResponse:
        return ProviderResponse(
            id=provider.id,
            name=provider.name,
            kind=provider.kind,
            base_url=provider.base_url,
            enabled=provider.enabled,
            configured=self.secret_store.exists(provider.api_key_ref),
            created_at=provider.created_at,
            updated_at=provider.updated_at,
            models=[
                {
                    "id": model.id,
                    "model_name": model.model_name,
                    "display_name": model.display_name,
                    "capabilities": model.capabilities_json,
                    "enabled": model.enabled,
                }
                for model in provider.models
            ],
        )
