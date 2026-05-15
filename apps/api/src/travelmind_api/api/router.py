from fastapi import APIRouter

from travelmind_api.api.routes import account, auth, community, exports, jobs, llm, search, settings, trips

router = APIRouter()
router.include_router(auth.router)
router.include_router(account.router)
router.include_router(settings.router)
router.include_router(trips.router)
router.include_router(community.router)
try:
    from travelmind_api.api.routes import images
except RuntimeError:  # Optional multipart/image dependencies are not always installed in MVP environments.
    images = None
if images is not None:
    router.include_router(images.router)
router.include_router(search.router)
router.include_router(exports.router)
router.include_router(jobs.router)
router.include_router(llm.router)
