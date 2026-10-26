"""Public PAI C entry points; callers retain their existing scheduling."""


async def handle_student_message(workspace_id, event_data):
    from app.pai_c.runtime import run_counselor
    return await run_counselor(workspace_id, event_data)


async def handle_research_result(workspace_id, history, handoff):
    from app.pai_c.handoff import explain_result
    return await explain_result(workspace_id, history, handoff)


async def handle_document_update(*args, **kwargs):
    from app.pai_c.posting import send_to_student
    return await send_to_student(*args, **kwargs)
