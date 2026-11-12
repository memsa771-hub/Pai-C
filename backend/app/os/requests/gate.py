"""The student's needs gate (P1-T8, D-w1). No new flag: the gate is on when the OS `counsellor` module is on, a host
StudentFacts adapter is configured and that adapter answers for this student. It answers only while the host's own
`CONNECT_STUDENT_FACTS` is on, and the worker loads the same adapter, so the API and the worker agree."""

from sqlalchemy import Engine

from app.os.contracts.student_facts import StudentFactsV1


def on(student_ref: str, *, engine: Engine, tenant_id: str) -> StudentFactsV1 | None:
    """The student's facts while the gate is on, else None."""
    from app.os.ports import student_facts  # late: the ports import the service layer's neighbours

    return student_facts.host_facts(student_ref, engine=engine, tenant_id=tenant_id)
