"""brain/api/routes/schema.py — Dynamic UI schema endpoint.
"""

from fastapi import APIRouter
from brain.api.models import DynamicSchemaResponse
from brain.api.services.config_service import get_dynamic_schema

router = APIRouter(tags=["Schema"])


@router.get("/schema", response_model=DynamicSchemaResponse)
def get_schema_endpoint():
    return get_dynamic_schema()
