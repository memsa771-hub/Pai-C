"""Tool handler that delegates research to PAI Operator (app/services/operator.py).

A thin wrapper: ExecutionRun state and durable scheduling live in the service
module. This file only adapts the (ctx, args) tool-call shape to it.
"""


async def delegate(ctx, args):
    from app.services import operator

    return await operator.delegate(
        ctx,
        args.get("objective", ""),
        args.get("constraints"),
        args.get("context_refs"),
        args.get("intent"),
        args.get("task_type"),
    )
