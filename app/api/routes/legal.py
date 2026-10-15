"""Versioned privacy / AI intended-use notices."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.schemas.api import LegalNoticeListResponse, LegalNoticeMeta, LegalNoticeOut
from app.services.legal_notices import get_notice, list_notice_ids

router = APIRouter(prefix="/legal", tags=["legal"])


@router.get("/notices", response_model=LegalNoticeListResponse)
def legal_notice_index() -> LegalNoticeListResponse:
    return LegalNoticeListResponse(
        notices=[LegalNoticeMeta(**item) for item in list_notice_ids()]
    )


@router.get("/notices/{notice_id}", response_model=LegalNoticeOut)
def legal_notice_get(
    notice_id: str,
    lang: str = Query(default="en", max_length=8),
) -> LegalNoticeOut:
    return LegalNoticeOut(**get_notice(notice_id, lang=lang))
