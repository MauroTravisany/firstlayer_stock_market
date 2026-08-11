"""WP-02 Strategy Brain entrypoint with experiment-registry instrumentation."""

import os

import legacy_main as legacy

from experiment_registry_adapter import install


install(legacy)


def main(request):
    """Delegate to Strategy Brain after installing the audit registry."""
    return legacy.main(request)


if __name__ == "__main__":
    from functions_framework import create_app

    port = int(os.environ.get("PORT", 8080))
    app = create_app("main")
    app.run(host="0.0.0.0", port=port)
