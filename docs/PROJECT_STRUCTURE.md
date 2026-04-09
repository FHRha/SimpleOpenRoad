# AI Gateway Router — Proposed Project Structure

```text
SimpleOpenRoad/
  app/
    __init__.py
    main.py

    api/
      __init__.py
      deps.py
      middleware.py
      routes_public.py
      routes_admin.py
      schemas_openai.py
      schemas_admin.py

    cli/
      __init__.py
      app.py
      commands_init.py
      commands_start.py
      commands_doctor.py
      commands_providers.py
      commands_keys.py
      commands_routes.py
      commands_config.py
      commands_logs.py
      commands_stats.py
      commands_health.py
      commands_menu.py

    config/
      __init__.py
      loader.py
      models.py
      runtime.py

    core/
      __init__.py
      types.py
      errors.py
      constants.py
      security.py
      utils.py

    providers/
      __init__.py
      base.py
      registry.py
      openai_compatible.py
      gemini.py
      github_models.py
      openrouter.py

    router/
      __init__.py
      engine.py
      selector.py
      alias_resolver.py
      policy.py
      classifier.py
      backoff.py

    registry/
      __init__.py
      keys.py
      providers.py

    health/
      __init__.py
      checker.py
      scheduler.py

    storage/
      __init__.py
      db.py
      schema.sql
      repositories/
        __init__.py
        keys_repo.py
        health_repo.py
        attempts_repo.py
        stats_repo.py

    observability/
      __init__.py
      logging.py
      metrics.py

    services/
      __init__.py
      gateway_service.py
      admin_service.py

  config/
    config.example.yaml

  tests/
    __init__.py
    unit/
      test_config_loader.py
      test_error_classifier.py
      test_selector.py
      test_alias_resolver.py
    integration/
      test_api_chat.py
      test_api_responses.py
      test_failover_flow.py
      test_cli_commands.py
    fixtures/
      sample_config.yaml

  scripts/
    bootstrap.py

  docs/
    REQUIREMENTS.md
    ARCHITECTURE.md
    IMPLEMENTATION_PLAN.md
    PROJECT_STRUCTURE.md

  .env.example
  .gitignore
  pyproject.toml
  README.md
```

Notes:
- `services/` is the orchestration layer used by both API and CLI.
- `providers/` and `router/` are isolated and independently testable.
- `storage/` keeps SQLite concerns away from domain logic.
- `observability/` can be reused later by a web dashboard.
