"""Bob Manager — Lab tracked-wallet access routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import DbSession, get_current_user
from app.repositories.lab_repo import LabRepository
from app.schemas.web3 import (
    LabWeb3AccessCreate,
    LabWeb3AccessResponse,
    TrackedWalletCandidateResponse,
)
from app.services.authorization import Permission, check_permission
from app.services.web3_access_service import Web3AccessService
from app.services.web3_service import get_wallet_for_user

router = APIRouter(tags=["labs"])


@router.get("/labs/{lab_id}/web3-access", response_model=list[LabWeb3AccessResponse])
async def list_lab_web3_access(lab_id: UUID, db: DbSession, user: dict = Depends(get_current_user)):
    lab = await LabRepository(db).get_by_id(lab_id)
    if not lab:
        raise HTTPException(404, "Lab not found")
    check_permission(user, lab.acl, Permission.VIEW)
    return await Web3AccessService(db).list_lab_access(lab_id)


@router.get("/labs/{lab_id}/web3-access/candidates", response_model=list[TrackedWalletCandidateResponse])
async def list_lab_web3_candidates(lab_id: UUID, db: DbSession, user: dict = Depends(get_current_user)):
    lab = await LabRepository(db).get_by_id(lab_id)
    if not lab:
        raise HTTPException(404, "Lab not found")
    check_permission(user, lab.acl, Permission.EDIT)
    return await Web3AccessService(db).list_candidate_wallets(user)


@router.post(
    "/labs/{lab_id}/web3-access",
    response_model=list[LabWeb3AccessResponse],
    status_code=status.HTTP_201_CREATED,
)
async def grant_lab_web3_access(
    lab_id: UUID,
    data: LabWeb3AccessCreate,
    db: DbSession,
    user: dict = Depends(get_current_user),
):
    if not data.wallet_ids:
        raise HTTPException(400, "wallet_ids is required")

    lab = await LabRepository(db).get_by_id(lab_id)
    if not lab:
        raise HTTPException(404, "Lab not found")
    check_permission(user, lab.acl, Permission.EDIT)

    for wallet_id in data.wallet_ids:
        wallet = await get_wallet_for_user(db, wallet_id, user, permission=Permission.VIEW)
        if wallet is None:
            raise HTTPException(404, f"Wallet {wallet_id} not found")

    try:
        rows = await Web3AccessService(db).grant_lab_access(lab_id, data.wallet_ids)
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc))
    await db.commit()
    return rows


@router.delete("/labs/{lab_id}/web3-access/{wallet_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_lab_web3_access(
    lab_id: UUID,
    wallet_id: UUID,
    db: DbSession,
    user: dict = Depends(get_current_user),
):
    lab = await LabRepository(db).get_by_id(lab_id)
    if not lab:
        raise HTTPException(404, "Lab not found")
    check_permission(user, lab.acl, Permission.EDIT)

    deleted = await Web3AccessService(db).revoke_lab_access(lab_id, wallet_id)
    if not deleted:
        raise HTTPException(404, "Access entry not found")
    await db.commit()