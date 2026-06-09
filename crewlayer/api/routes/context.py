from fastapi import APIRouter, HTTPException, status

from crewlayer.api.deps import DbDep, TenantDep
from crewlayer.api.schemas.context import (
    ContextEntryResponse,
    ContextNamespaceResponse,
    ContextWrite,
)
from crewlayer.core.context.blackboard import Blackboard, VersionConflictError

router = APIRouter()


@router.put(
    "/{namespace}/{key}",
    response_model=ContextEntryResponse,
)
async def write_entry(
    namespace: str,
    key: str,
    body: ContextWrite,
    tenant: TenantDep,
    db: DbDep,
) -> ContextEntryResponse:
    """Write or overwrite a context entry. Optionally enforce optimistic locking
    by providing expected_version (use 0 to assert the key must not yet exist)."""
    bb = Blackboard(db)
    try:
        entry = await bb.write(
            tenant_id=tenant.id,
            namespace=namespace,
            key=key,
            value=body.value,
            written_by=body.written_by,
            expires_at=body.expires_at,
            expected_version=body.expected_version,
        )
    except VersionConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Version conflict: expected {exc.expected}, current is {exc.actual}",
        )
    await db.commit()
    await db.refresh(entry)
    return ContextEntryResponse.model_validate(entry)


@router.get(
    "/{namespace}/{key}",
    response_model=ContextEntryResponse,
)
async def read_entry(
    namespace: str,
    key: str,
    tenant: TenantDep,
    db: DbDep,
) -> ContextEntryResponse:
    """Read a context entry. Returns 404 if absent or expired."""
    bb = Blackboard(db)
    entry = await bb.read(tenant.id, namespace, key)
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entrada no encontrada")
    return ContextEntryResponse.model_validate(entry)


@router.get(
    "/{namespace}",
    response_model=ContextNamespaceResponse,
)
async def list_namespace(
    namespace: str,
    tenant: TenantDep,
    db: DbDep,
) -> ContextNamespaceResponse:
    """List all non-expired entries in a namespace, ordered by key."""
    bb = Blackboard(db)
    entries = await bb.list_namespace(tenant.id, namespace)
    return ContextNamespaceResponse(
        namespace=namespace,
        entries=[ContextEntryResponse.model_validate(e) for e in entries],
        count=len(entries),
    )


@router.delete(
    "/{namespace}/{key}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_entry(
    namespace: str,
    key: str,
    tenant: TenantDep,
    db: DbDep,
) -> None:
    """Delete a context entry."""
    bb = Blackboard(db)
    deleted = await bb.delete(tenant.id, namespace, key)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entrada no encontrada")
    await db.commit()
