"""Synthetic policy read APIs."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.api import PolicyDetail, PolicyListResponse, PolicyPath
from app.services.records import get_policy_detail, list_policy_summaries

router = APIRouter(prefix="/policies", tags=["policies"])


@router.get("", response_model=PolicyListResponse)
def list_policies(db: Session = Depends(get_db)) -> PolicyListResponse:
    return list_policy_summaries(db)


@router.get("/{policy_id}", response_model=PolicyDetail)
def get_policy(policy_id: PolicyPath, db: Session = Depends(get_db)) -> PolicyDetail:
    return get_policy_detail(db, policy_id)
