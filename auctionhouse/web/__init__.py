"""The public auction house pages (routes.py), mounted on the oauth server."""


def register_routes(app):
    """Mount /ah (imported lazily, like raidanalysis.web)."""
    from .routes import register_routes as register
    register(app)


__all__ = ['register_routes']
