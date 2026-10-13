"""Routing and catalog identity module."""

from brain.routing.classifier import (
    ModelModality,
    NON_AGENTIC_MODALITIES,
    ModelClassification,
    classify_model_capabilities,
    classify_from_probe,
    is_model_agentic,
)
from brain.routing.identity import (
    CanonicalIdentityResolver,
    CanonicalModelIdentity,
    resolve_canonical_identity,
)
from brain.routing.catalog import (
    Route,
    CanonicalModel,
    CatalogAuditor,
)
from brain.routing.scorer import (
    ModelScorer,
    QualityScore,
)
from brain.routing.engine import (
    RoutingRequirements,
    RouteDecision,
    DynamicRoutingEngine,
)

__all__ = [
    "ModelModality",
    "NON_AGENTIC_MODALITIES",
    "ModelClassification",
    "classify_model_capabilities",
    "classify_from_probe",
    "is_model_agentic",
    "CanonicalIdentityResolver",
    "CanonicalModelIdentity",
    "resolve_canonical_identity",
    "Route",
    "CanonicalModel",
    "CatalogAuditor",
    "ModelScorer",
    "QualityScore",
    "RoutingRequirements",
    "RouteDecision",
    "DynamicRoutingEngine",
]
