"""Single dispatch over the existing durable Postgres queue."""
from app.capabilities import get_capability_registry
from app.capabilities.manifest import validate_instance


def _system(job_type, registry=None):
    contract = (registry or get_capability_registry()).get(job_type)
    if contract is None or contract.kind != "system":
        raise LookupError(f"No system capability registered for job type: {job_type}")
    return contract


def _validate(contract, payload):
    # Optional nulls historically mean "use handler default"; preserve them on
    # the job while checking non-null supplied fields against the typed contract.
    validate_instance(contract.input_schema,
                      {key: value for key, value in payload.items() if value is not None},
                      "job payload")


def enqueue(db, job_type, payload=None, **kwargs):
    from app.jobs.service import BackgroundJobService
    contract = _system(job_type)
    validate_instance({"type": "object"}, payload if payload is not None else {}, "job payload")
    _validate(contract, payload if payload is not None else {})
    return BackgroundJobService(db).enqueue(job_type=job_type, payload=payload, **kwargs)


async def run(job, db, *, registry=None):
    contract = _system(job.job_type, registry)
    payload = job.payload if job.payload is not None else {}
    validate_instance({"type": "object"}, payload, "job payload")
    _validate(contract, payload)
    # Handler signature, transaction, ordering locks and worker retries unchanged.
    return await contract.handler(job, db)
