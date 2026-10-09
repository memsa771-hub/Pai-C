# Application Workspace backend

This package owns student-managed college and application planning. It is
separate from `app/pai_c`, Student Profile and Vault.

| File | Responsibility |
| --- | --- |
| `schemas.py` | Validated request shapes |
| `access.py` | Workspace access and student-write checks |
| `queries.py` | Scoped lookups shared by the modules |
| `catalog.py` | Institution search and saved colleges |
| `plans.py` | Per-program plans and requirements |
| `calendar.py` | Application calendar projection |
| `operations.py` | Links to existing tasks, workflows and routines |
| `serializers.py` | API response projections |
| `context.py` | Bounded current plan context for scheduled PAI reviews |
| `__init__.py` | Assembles one API router under `/v1/application-workspace` |

`app/routers/application_workspace.py` is only a compatibility entry point
for the project's router registration convention. The shared ORM models and
Alembic migrations stay in their existing central locations. Deadline
aggregation and reminders belong to the separate `app/deadlines` package.

There is no seeded institution list, country checklist or fabricated deadline.
Student-entered records retain their origin, and external submissions require
a future integration with approval and a verifiable receipt.
