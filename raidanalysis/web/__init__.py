def register_routes(app):
    """Mount the raid analysis admin pages (imported lazily so the pure view helpers stay importable alone)."""
    from .routes import register_routes as register
    register(app)


__all__ = ['register_routes']
