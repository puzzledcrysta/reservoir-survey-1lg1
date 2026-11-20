from fastapi import APIRouter, Response
from app.inputs import MergeRequest, MergeReview
from .service import merge
from .repository import get, list_all
from .decisions import decide, timeline
from .bundle import bundle

router = APIRouter()


@router.post('/api/merges')
def create_merge(request: MergeRequest):
    return merge(request.run_ids, request.roles)


@router.get('/api/merges')
def merges():
    return list_all()


@router.get('/api/merges/{merge_id}')
def detail(merge_id: str):
    return get(merge_id)


@router.get('/api/review/merge/{merge_id}')
def reviews(merge_id: str):
    return timeline(merge_id)


@router.post('/api/review/merge/{merge_id}')
def commit(merge_id: str, review: MergeReview):
    return decide(merge_id, review.version, review.decision, review.note)


@router.get('/api/export/merge/{merge_id}')
def export(merge_id: str):
    return Response(bundle(merge_id), media_type='application/json',
                    headers={'Content-Disposition': f'attachment; filename="merge-{merge_id}.json"'})
