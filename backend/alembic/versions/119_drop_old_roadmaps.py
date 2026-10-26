"""Drop the old roadmap tables (founder-approved 26 Oct 2026).

Revision ID: 119
Revises: 118

The roadmap engine and `pai_route_decisions` (118) replaced them; no code reads
or writes them any more. Drops `pai_decision_records`, `pai_roadmap_student_state`,
the `pai_possibilities.roadmap_id` column and `pai_roadmaps`, in FK-safe order.

Clean-ups ride along because the dropped system left them behind. They run
before the drops, in this order:
- paths still `chosen` by the old system with no active route decision go back
  to `saved` (nothing else could ever move them out of `chosen`);
- counselor journeys in CHOSEN with no active route decision go back to
  PROPOSED (DIRECTION if their Mirror is not confirmed) and lose the old goal,
  as a withdraw does;
- counselor journeys parked in the old research wait (RESEARCHING, ASSESSING,
  NEEDS_INFO) with a confirmed Mirror move to CHOSEN with the route as their
  goal when the workspace has an active route decision, else to PROPOSED;
- every stage moved above gets a `journey.stage_changed` event, as the app writes;
- unfinished `roadmap_research` runs are marked failed with a reason (a failed
  run is terminal, so its queued job finishes without posting to chat);
- queued background jobs whose type has no handler any more are deleted
  (pending or running; succeeded, failed and cancelled rows are history).

Downgrade recreates the tables empty (084 -> 111 shapes). It does not bring
back the clean-ups.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "119"
down_revision = "118"
branch_labels = depends_on = None

_COUNSELOR = "journey_type = 'counselor_decision'"
_WAITING = "current_stage IN ('RESEARCHING', 'ASSESSING', 'NEEDS_INFO')"
_CONFIRMED = "counselor_summary_draft->>'status' = 'confirmed'"
_DECISION = ("FROM pai_route_decisions d "
             "WHERE d.workspace_id = pai_student_journeys.workspace_id AND d.withdrawn_at IS NULL")
_ACTIVE_DECISION = f"EXISTS (SELECT 1 {_DECISION})"


def _move(where: str, to: str, also: str = "") -> tuple[str, str]:
    """A stage move as the app makes it: the stage_changed event (written
    first, while the old stage is still there to read), then the update."""
    event = ("INSERT INTO pai_student_journey_events (id, journey_id, workspace_id, event_type, payload, actor, "
             "created_at) SELECT CAST(gen_random_uuid() AS TEXT), id, workspace_id, 'journey.stage_changed', "
             f"jsonb_build_object('from', current_stage, 'to', {to}), 'system:migration_119', NOW() "
             f"FROM pai_student_journeys WHERE {where}")
    update = f"UPDATE pai_student_journeys SET current_stage = {to}, {also}updated_at = NOW() WHERE {where}"
    return event, update


RESET_ORPHAN_PATHS = ("UPDATE pai_possibilities SET status = 'saved', updated_at = NOW() WHERE status = 'chosen' "
                      "AND id NOT IN (SELECT possibility_id FROM pai_route_decisions "
                      "WHERE withdrawn_at IS NULL AND possibility_id IS NOT NULL)")
UNCHOOSE = _move(f"{_COUNSELOR} AND current_stage = 'CHOSEN' AND NOT {_ACTIVE_DECISION}",
                 f"CASE WHEN {_CONFIRMED} THEN 'PROPOSED' ELSE 'DIRECTION' END",
                 "active_goal = NULL, current_objective = NULL, ")
# CHOSEN first: MOVE_TO_PROPOSED then only sees journeys still waiting.
MOVE_TO_CHOSEN = _move(f"{_COUNSELOR} AND {_WAITING} AND {_CONFIRMED} AND {_ACTIVE_DECISION}", "'CHOSEN'",
                       f"current_objective = (SELECT d.title {_DECISION}), "
                       "active_goal = (SELECT jsonb_build_object('route_decision_id', d.id, 'field_key', d.field_key, "
                       f"'title', d.title, 'route', d.route) {_DECISION}), ")
MOVE_TO_PROPOSED = _move(f"{_COUNSELOR} AND {_WAITING} AND {_CONFIRMED}", "'PROPOSED'")
RETIRE_RUNS = ("UPDATE execution_runs SET status = 'failed', pending_action = NULL, "
               "error = 'Retired: roadmap research was replaced by the roadmap engine', "
               "completed_at = NOW(), updated_at = NOW() "
               "WHERE task_type = 'roadmap_research' AND status NOT IN ('completed', 'failed')")
DELETE_DEAD_JOBS = ("DELETE FROM background_jobs WHERE job_type IN ('roadmaps.mark_stale', 'research.refresh_stale') "
                    "AND status IN ('pending', 'running')")
CLEANUP = (RESET_ORPHAN_PATHS, *UNCHOOSE, *MOVE_TO_CHOSEN, *MOVE_TO_PROPOSED, RETIRE_RUNS, DELETE_DEAD_JOBS)


def upgrade():
    for statement in CLEANUP:
        op.execute(statement)

    op.drop_index("idx_decision_workspace_current", table_name="pai_decision_records")
    op.drop_table("pai_decision_records")
    op.drop_index("idx_roadmap_student_state_journey", table_name="pai_roadmap_student_state")
    op.drop_index("uq_roadmap_chosen_per_journey", table_name="pai_roadmap_student_state")
    op.drop_table("pai_roadmap_student_state")
    op.drop_column("pai_possibilities", "roadmap_id")
    for index in ("uq_roadmaps_journey_lane", "idx_roadmaps_requirement_set", "idx_roadmaps_run",
                  "idx_roadmaps_workspace_journey"):
        op.drop_index(index, table_name="pai_roadmaps")
    op.drop_table("pai_roadmaps")


def downgrade():
    op.create_table(
        "pai_roadmaps",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("workspace_id", sa.UUID(as_uuid=False), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("journey_id", sa.Text(), sa.ForeignKey("pai_student_journeys.id", ondelete="CASCADE"), nullable=False),
        sa.Column("goal_id", sa.Text()),
        sa.Column("lane", sa.Text()),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("route", JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("fit_level", sa.Text()),
        sa.Column("fit_dimensions", JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("gaps", JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("steps", JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("total_cost", JSONB()),
        sa.Column("time_to_start", sa.Text()),
        sa.Column("risks", JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("sources", JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("scholarships", JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("generation_status", sa.Text(), nullable=False, server_default=sa.text("'generating'")),
        sa.Column("stale_reason", sa.Text()),
        sa.Column("execution_run_id", sa.Text(), sa.ForeignKey("execution_runs.id", ondelete="SET NULL")),
        sa.Column("requirement_set_id", sa.Text(), sa.ForeignKey("pai_requirement_sets.id", ondelete="SET NULL")),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.CheckConstraint("origin IN ('stated_goal', 'alternative', 'family_wish', 'student_added', 'operator_suggested')", name="ck_roadmap_origin"),
        sa.CheckConstraint("fit_level IS NULL OR fit_level IN ('strong', 'partial', 'weak', 'not_possible_yet', 'unconfirmed')", name="ck_roadmap_fit"),
        sa.CheckConstraint("generation_status IN ('generating', 'ready', 'needs_info', 'failed', 'stale')", name="ck_roadmap_generation_status"),
        sa.CheckConstraint("version > 0", name="ck_roadmap_version"),
    )
    op.create_index("idx_roadmaps_workspace_journey", "pai_roadmaps", ["workspace_id", "journey_id", "updated_at"])
    op.create_index("idx_roadmaps_run", "pai_roadmaps", ["execution_run_id"])
    op.create_index("idx_roadmaps_requirement_set", "pai_roadmaps", ["requirement_set_id"])
    op.create_index("uq_roadmaps_journey_lane", "pai_roadmaps", ["workspace_id", "journey_id", "lane"], unique=True)

    op.add_column("pai_possibilities", sa.Column("roadmap_id", sa.Text(),
                                                 sa.ForeignKey("pai_roadmaps.id", ondelete="SET NULL")))

    op.create_table(
        "pai_roadmap_student_state",
        sa.Column("roadmap_id", sa.Text(), sa.ForeignKey("pai_roadmaps.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("journey_id", sa.Text(), sa.ForeignKey("pai_student_journeys.id", ondelete="CASCADE"), nullable=False),
        sa.Column("favorite", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("exploring", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("dismissed_at", sa.DateTime(timezone=True)),
        sa.Column("chosen_at", sa.DateTime(timezone=True)),
        sa.Column("focused_at", sa.DateTime(timezone=True)),
        sa.Column("presented_at", sa.DateTime(timezone=True)),
    )
    op.create_index("uq_roadmap_chosen_per_journey", "pai_roadmap_student_state", ["journey_id"], unique=True,
                    postgresql_where=sa.text("chosen_at IS NOT NULL"))
    op.create_index("idx_roadmap_student_state_journey", "pai_roadmap_student_state", ["journey_id"])

    op.create_table(
        "pai_decision_records",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("workspace_id", sa.UUID(as_uuid=False), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("journey_id", sa.Text(), sa.ForeignKey("pai_student_journeys.id", ondelete="CASCADE"), nullable=False),
        sa.Column("roadmap_id", sa.Text(), sa.ForeignKey("pai_roadmaps.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("roadmap_version", sa.Integer(), nullable=False),
        sa.Column("confirmed_summary", JSONB(), nullable=False),
        sa.Column("real_objective", sa.Text(), nullable=True),
        sa.Column("accepted_gaps", JSONB(), nullable=False),
        sa.Column("accepted_risks", JSONB(), nullable=False),
        sa.Column("assumptions", JSONB(), nullable=False),
        sa.Column("choice_channel", sa.Text(), nullable=False),
        sa.Column("chosen_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("roadmap_version > 0", name="ck_decision_roadmap_version"),
        sa.CheckConstraint("choice_channel IN ('chat', 'voice', 'roadmaps')", name="ck_decision_choice_channel"),
        sa.UniqueConstraint("journey_id", "roadmap_id", "roadmap_version", name="uq_decision_route_version"),
    )
    op.create_index("idx_decision_workspace_current", "pai_decision_records", ["workspace_id", "chosen_at"])
