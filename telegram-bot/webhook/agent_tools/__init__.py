"""Agent tools API — combined router.

Split from the former 3714-line agent_tools_api.py into domain modules
(see docs/superpowers/plans/2026-09-06-agent-tools-api-split.md). This
__init__.py re-exports a single `router` so the mount point in
apple_health.py needs only a one-line import-path change.
"""

from fastapi import APIRouter

from .auth import router as _auth_router
from .nutrition import router as _nutrition_router
from .supplements import router as _supplements_router
from .feedback import router as _feedback_router
from .vitals import router as _vitals_router
from .glucose import router as _glucose_router
from .kb import router as _kb_router
from .agent_meta import router as _agent_meta_router
from .reports import router as _reports_router
from .dashboard import router as _dashboard_router
from .menstrual import router as _menstrual_router
from .sleep import router as _sleep_router
from .biomarkers import router as _biomarkers_router
from .workouts import router as _workouts_router
from .profile import router as _profile_router
from .environment import router as _environment_router

router = APIRouter()
for _sub_router in (
    _auth_router,
    _nutrition_router,
    _supplements_router,
    _feedback_router,
    _vitals_router,
    _glucose_router,
    _kb_router,
    _agent_meta_router,
    _reports_router,
    _dashboard_router,
    _menstrual_router,
    _sleep_router,
    _biomarkers_router,
    _workouts_router,
    _profile_router,
    _environment_router,
):
    router.include_router(_sub_router)
