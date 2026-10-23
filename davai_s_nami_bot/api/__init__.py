def register_routers(app, prefix="/api"):
    from .ai import router as ai_router
    from .auth import router as auth_router
    from .cities import router as cities_router
    from .content_generator import router as content_generator_router
    from .event import router as events_router
    from .health import router as health_router
    from .images import router as images_router
    from .places import router as places_router
    from .search import router as search_router
    from .tasks import router as tasks_router
    from .users import router as users_router

    for r in [
        auth_router,
        cities_router,
        users_router,
        tasks_router,
        events_router,
        places_router,
        search_router,
        images_router,
        ai_router,
        content_generator_router,
        health_router,
    ]:
        app.include_router(r, prefix=prefix)
