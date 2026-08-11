"""Strategy Brain entrypoint with WP-02 experiment registry installed."""

import os

import main as legacy
from experiment_registry_adapter import install

install(legacy)


def main(request):
    return legacy.main(request)


if __name__ == "__main__":
    from functions_framework import create_app

    port = int(os.environ.get("PORT", 8080))
    app = create_app("main")
    app.run(host="0.0.0.0", port=port)
