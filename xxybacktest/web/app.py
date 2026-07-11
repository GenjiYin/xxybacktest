"""Flask 应用入口"""
from flask import Flask
from pathlib import Path


def create_app():
    app = Flask(__name__, template_folder=str(Path(__file__).parent / 'templates'))

    from .routes.dashboard import dashboard_bp
    from .routes.account import account_bp
    from .routes.api import api_bp
    from .routes.tasks import tasks_bp
    from .routes.factor import factor_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(account_bp)
    app.register_blueprint(api_bp, url_prefix='/api')
    app.register_blueprint(tasks_bp)
    # factor_bp 自带完整路径(/factors 与 /api/factors), 不加前缀
    app.register_blueprint(factor_bp)

    return app
