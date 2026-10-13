"""Public PAI C entry points; callers retain their existing scheduling."""


async def handle_student_message(workspace_id, event_data):
    from app.pai_c.runtime import run_counselor
    return await run_counselor(workspace_id, event_data)


async def handle_research_result(workspace_id, history, handoff):
    from app.pai_c.handoff import explain_result
    return await explain_result(workspace_id, history, handoff)


async def handle_roadmap_discussion(db, workspace, roadmap_id, title):
    from app.pai_c.posting import _build_conversation_context, send_to_student
    from app.pai_c.deep.turn import run_deep_turn
    from app.pai_c.deep.turn_input import CounselorTurnInput
    from app.services.pai import PAI_AGENT_NAME, PAI_PRIMARY_CHANNEL

    target = f"channel/{PAI_PRIMARY_CHANNEL}"
    history = _build_conversation_context(db, str(workspace.id), target,
                                        PAI_AGENT_NAME, exclude_event_id="", max_chars=3000)
    turn = CounselorTurnInput(
        channel=target, workspace_id=str(workspace.id),
        student_text=f"I opened the roadmap named {title}.",
        attachments=(), session_id=None, source_event_id="",
        timestamp=None, source=f"human:{workspace.owner_user_id}",
    )
    response = await run_deep_turn(db, turn, roadmap_id=roadmap_id, history=history)
    if response.reply:
        return await send_to_student(db, str(workspace.id), target,
                                     PAI_AGENT_NAME, response.reply, depth=0)
    return None


async def handle_document_update(*args, **kwargs):
    from app.pai_c.posting import send_to_student
    return await send_to_student(*args, **kwargs)
