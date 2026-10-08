# PR 3 deep module literal audit

Every Python AST string and numeric literal in `backend/app/counseling/deep/*.py` is listed below, including repeated occurrences and docstrings. Boolean and null literals are not strings or numbers. These are protocol identifiers, section labels, regex syntax, storage fields, and bounded generic operations. No student words, persona names, academic subjects, countries, or language-specific text select a conversation path. Tunable model, budget, history, research, and language settings live in `app/config.py` with environment overrides.

Inventory: **537 literal occurrences** across 11 Python modules.

| File | Line | Literal | Why retained |
| --- | ---: | --- | --- |
| __init__.py | 1 | <code>&#x27;Shared building blocks for the staged deep Counselor implementation.&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| actions.py | 1 | <code>&#x27;Validate and record model-requested Counselor actions without model calls.&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 16 | <code>&#x27;ask_research&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 16 | <code>&#x27;mirror&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 16 | <code>&#x27;none&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 16 | <code>&#x27;rethink&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 16 | <code>&#x27;wellbeing&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 22 | <code>&#x27;counselor.action.&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 22 | <code>&#x27;openagents:pai&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 23 | <code>&#x27;status&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 24 | <code>&#x27;trigger_event_id&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 25 | <code>&#x27;private&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 25 | <code>1000</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 31 | <code>500</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 32 | <code>&#x27;ask_research&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 32 | <code>&#x27;ignored&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 32 | <code>&#x27;invalid_question&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 33 | <code>&#x27;ignored&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 35 | <code>&#x27;active&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 39 | <code>&#x27;ignored&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 42 | <code>&#x27;counselor.action.ask_research&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 43 | <code>&#x27;trigger_event_id&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 44 | <code>1</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 47 | <code>&#x27;duplicate&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 49 | <code>0</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 49 | <code>0</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 49 | <code>0</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 49 | <code>0</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 49 | <code>1000</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 52 | <code>&#x27;counselor.action.ask_research&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 54 | <code>&#x27;accepted&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 54 | <code>&#x27;pending&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 54 | <code>&#x27;status&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 55 | <code>0</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 57 | <code>&#x27;ask_research&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 57 | <code>&#x27;daily_limit&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 57 | <code>&#x27;ignored&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 58 | <code>&#x27;rate_limited&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 65 | <code>&#x27;counselor.action.ask_research&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 65 | <code>&#x27;openagents:pai&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 66 | <code>&#x27;pending&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 66 | <code>&#x27;status&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 67 | <code>&#x27;trigger_event_id&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 68 | <code>&#x27;private&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 68 | <code>1000</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 78 | <code>&#x27;channel/&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 80 | <code>&#x27;operator.delegate&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 85 | <code>&#x27;operator.delegate&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 86 | <code>&#x27;Research this one student question using official sources: &#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 86 | <code>&#x27;objective&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 87 | <code>&#x27;academic_planning&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 87 | <code>&#x27;intent&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 87 | <code>&#x27;question_research&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 87 | <code>&#x27;task_type&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 88 | <code>&#x27;constraints&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 88 | <code>&#x27;journey_id&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 89 | <code>&#x27;question_event_id&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 90 | <code>&#x27;context_refs&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 90 | <code>&#x27;memory&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 90 | <code>&#x27;vault&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 93 | <code>&#x27;counselor: question research delegation failed&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 94 | <code>&#x27;ok&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 95 | <code>&#x27;ok&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 97 | <code>&#x27;accepted&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 97 | <code>&#x27;failed&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 97 | <code>&#x27;status&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 98 | <code>&#x27;data&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 98 | <code>&#x27;run_id&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 98 | <code>&#x27;run_id&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 101 | <code>&#x27;accepted&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 101 | <code>&#x27;failed&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 106 | <code>&#x27;type&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 108 | <code>&#x27;counselor: unknown deep action type=%s&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 108 | <code>40</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 109 | <code>&#x27;ignored&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 109 | <code>&#x27;none&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 110 | <code>&#x27;none&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 111 | <code>&#x27;none&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 112 | <code>&#x27;mirror&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 114 | <code>&#x27;counselor: mirror requested ready=%s&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 115 | <code>&#x27;ignored&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 115 | <code>&#x27;requested&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 116 | <code>&#x27;not_ready&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 117 | <code>&#x27;ignored&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 117 | <code>&#x27;requested&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 118 | <code>&#x27;ask_research&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 119 | <code>&#x27;question&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 119 | <code>&#x27;research_question&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 121 | <code>&#x27;&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 122 | <code>&#x27;wellbeing&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 123 | <code>&#x27;recorded&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 124 | <code>&#x27;recorded&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 127 | <code>&#x27;&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 128 | <code>1</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 130 | <code>&#x27;ignored&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 130 | <code>&#x27;no_roadmaps&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 131 | <code>&#x27;ignored&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 137 | <code>&#x27;PROPOSED&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 138 | <code>0</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 139 | <code>&#x27;CHOSEN&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 141 | <code>&#x27;DIRECTION&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 142 | <code>&#x27;openagents:pai&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 145 | <code>&#x27;ignored&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 145 | <code>&#x27;stage_not_replannable&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 146 | <code>&#x27;ignored&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 149 | <code>&#x27;ignored&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 149 | <code>&#x27;replan_unavailable&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 150 | <code>&#x27;ignored&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 151 | <code>&#x27;accepted&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| actions.py | 152 | <code>&#x27;accepted&#x27;</code> | Action names, event fields, rate-limit accounting, or status codes; no student-topic matching. |
| context.py | 1 | <code>&#x27;Read-only, channel-neutral context for one deep Counselor turn.&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 24 | <code>&#x27;claims&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 24 | <code>&#x27;constraints&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 24 | <code>&#x27;coverage&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 24 | <code>&#x27;family&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 24 | <code>&#x27;open_questions&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 25 | <code>&#x27;depth_mode&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 25 | <code>&#x27;engagement_style&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 25 | <code>&#x27;mirror_ready&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 25 | <code>&#x27;person&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 25 | <code>&#x27;stated_goal&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 26 | <code>&#x27;drivers&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 26 | <code>&#x27;goal_history&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 26 | <code>&#x27;growth_areas&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 26 | <code>&#x27;hypotheses&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 26 | <code>&#x27;strengths&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 27 | <code>&#x27;emotional_notes&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 27 | <code>&#x27;learning_style&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 27 | <code>&#x27;values&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 27 | <code>&#x27;work_preferences&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 28 | <code>&#x27;chapter&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 28 | <code>&#x27;mirror_blockers&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 33 | <code>&#x27;Conservative transport-independent estimate; no tokenizer/model call.&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 34 | <code>&#x27;utf-8&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 34 | <code>4</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 38 | <code>&#x27;,&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 38 | <code>&#x27;:&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 41 | <code>350</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 52 | <code>&#x27;json&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 76 | <code>&#x27;display_name&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 76 | <code>&#x27;onboarding&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 76 | <code>&#x27;source&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 76 | <code>&#x27;value&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 78 | <code>&#x27;current_status&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 78 | <code>&#x27;date_of_birth&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 78 | <code>&#x27;full_name&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 78 | <code>&#x27;preferred_name&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 78 | <code>&#x27;status_category&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 79 | <code>&#x27;value&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 79 | <code>&#x27;value&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 80 | <code>&#x27;source&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 80 | <code>&#x27;source_type&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 80 | <code>&#x27;unknown&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 81 | <code>&#x27;value&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 81 | <code>&#x27;value&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 82 | <code>&#x27;source&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 82 | <code>&#x27;source_type&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 82 | <code>&#x27;unknown&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 83 | <code>&#x27;confidence&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 83 | <code>&#x27;verification&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 84 | <code>30</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 85 | <code>&#x27;value&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 86 | <code>&#x27;created_at&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 86 | <code>&#x27;evidence&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 86 | <code>&#x27;updated_at&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 87 | <code>&#x27;source&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 87 | <code>&#x27;source_type&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 87 | <code>&#x27;unknown&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 88 | <code>&#x27;unknown&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 88 | <code>&#x27;verification&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 88 | <code>&#x27;verification_status&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 89 | <code>5</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 91 | <code>&#x27;certification&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 91 | <code>&#x27;course&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 91 | <code>&#x27;education&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 91 | <code>&#x27;goal&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 91 | <code>&#x27;test_attempt&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 92 | <code>&#x27;achievement&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 92 | <code>&#x27;activity&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 92 | <code>&#x27;project&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 92 | <code>&#x27;skill&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 92 | <code>&#x27;work_experience&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 94 | <code>&#x27;facts&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 94 | <code>&#x27;identity_never_ask&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 94 | <code>&#x27;records&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 95 | <code>&#x27;open_profile_issues&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 95 | <code>&#x27;question&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 95 | <code>&#x27;question&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 95 | <code>&#x27;type&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 95 | <code>&#x27;type&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 96 | <code>5</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 99 | <code>8</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 106 | <code>&#x27;source_url&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 106 | <code>&#x27;url&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 107 | <code>&#x27;quote&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 107 | <code>&#x27;text&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 108 | <code>&#x27;checked_at&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 110 | <code>&#x27;source_url&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 110 | <code>&#x27;text&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 110 | <code>500</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 111 | <code>&#x27;checked_at&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 112 | <code>&#x27;label&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 112 | <code>&#x27;status&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 112 | <code>&#x27;unconfirmed&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 112 | <code>&#x27;verified&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 112 | <code>&#x27;verified&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 126 | <code>&#x27;facts&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 126 | <code>&#x27;open_requests&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 126 | <code>&#x27;roadmaps&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 129 | <code>&#x27;question_research&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 130 | <code>15</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 131 | <code>&#x27;journey_id&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 132 | <code>&#x27;completed&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 132 | <code>3</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 136 | <code>&#x27;open&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 138 | <code>5</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 139 | <code>&#x27;CHOSEN&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 139 | <code>&#x27;PROPOSED&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 140 | <code>&#x27;RESEARCHING&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 141 | <code>&#x27;confirmed&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 141 | <code>&#x27;status&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 147 | <code>5</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 148 | <code>&#x27;id&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 148 | <code>&#x27;title&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 149 | <code>&#x27;status&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 150 | <code>&#x27;sources&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 150 | <code>5</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 151 | <code>&#x27;url&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 153 | <code>&#x27;facts&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 153 | <code>&#x27;research_status&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 153 | <code>8</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 154 | <code>&#x27;question&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 154 | <code>&#x27;status&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 154 | <code>250</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 154 | <code>3</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 155 | <code>&#x27;roadmaps&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 156 | <code>&#x27;item_key&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 156 | <code>&#x27;open_requests&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 156 | <code>&#x27;reason&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 156 | <code>250</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 170 | <code>&#x27;Build every section from workspace-scoped reads; make no model calls.&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 173 | <code>&#x27;turn belongs to another workspace&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 175 | <code>&#x27;today&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 176 | <code>&#x27;language_policy&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 177 | <code>&#x27;,&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 177 | <code>&#x27;blocked_scripts&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 179 | <code>&#x27;replacement&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 180 | <code>&#x27;fallback_reply&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 182 | <code>&#x27;profile&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 185 | <code>&#x27;notebook&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 186 | <code>&#x27;active&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 187 | <code>&#x27;counselor_decision&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 188 | <code>&#x27;&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 191 | <code>&#x27;pai&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 193 | <code>1</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 194 | <code>&#x27;memory&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 195 | <code>&#x27;foreground&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 196 | <code>&#x27;latest_episode_summary&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 196 | <code>0</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 196 | <code>500</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 197 | <code>&#x27;open_threads&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 197 | <code>3</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 199 | <code>&#x27;research&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 200 | <code>&#x27;IDENTITY&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 200 | <code>&#x27;journey&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 200 | <code>&#x27;stage&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 201 | <code>&#x27;&lt;context&gt;\n&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 201 | <code>&#x27;\n&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 202 | <code>&#x27;&lt;&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 202 | <code>&#x27;&lt;/&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 202 | <code>&#x27;&gt;&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 202 | <code>&#x27;&gt;&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 203 | <code>&#x27;\n&lt;/context&gt;&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 205 | <code>1000</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| context.py | 206 | <code>&#x27;counselor_deep_context tokens=%s total_tokens=%d build_ms=%d&#x27;</code> | Context section tags, database field names, serialization, logging, or bounded reads; no student-topic matching. |
| notebook.py | 1 | <code>&#x27;Private, workspace-scoped Counselor Notebook persistence.\n\nCallers must supply the source student event. A stale writer receives a\nNotebookVersionConflict and must fetch the latest version before retrying.\n&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| notebook.py | 20 | <code>&#x27;The caller must refetch and recompute against a newer notebook.&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| notebook.py | 24 | <code>&#x27;The workspace does not exist or has been deleted.&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| notebook.py | 40 | <code>&#x27;active&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| notebook.py | 51 | <code>0</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| notebook.py | 58 | <code>&#x27;Validate, sanitize and atomically write one complete snapshot.\n\n        expected_version is optional for first-party callers that load and\n        apply in one operation. Long-lived callers should pass the version\n        returned by get, so stale writes never silently replace newer notes.\n        &#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| notebook.py | 68 | <code>&#x27;active&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| notebook.py | 77 | <code>&#x27;human:%&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| notebook.py | 80 | <code>&#x27;source_event_id must be a student event in this workspace&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| notebook.py | 82 | <code>&#x27;json&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| notebook.py | 84 | <code>&#x27;notebook must be an object&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| notebook.py | 87 | <code>&#x27;json&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| notebook.py | 88 | <code>&#x27;json&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| notebook.py | 89 | <code>&#x27;json&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| notebook.py | 90 | <code>&#x27;sanitization would erase the existing notebook&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| notebook.py | 92 | <code>&#x27;, found &#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| notebook.py | 92 | <code>&#x27;expected &#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| notebook.py | 93 | <code>1</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| notebook.py | 102 | <code>1</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| notebook.py | 104 | <code>&#x27;notebook changed during apply&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| notebook.py | 115 | <code>&#x27;notebook created during apply&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| notebook.py | 124 | <code>&quot;Purge private notes within the caller&#x27;s workspace-delete transaction.&quot;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| notebook_sanitize.py | 1 | <code>&#x27;Loss-minimizing, auditable cleanup before strict notebook validation.&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| notebook_sanitize.py | 28 | <code>&#x27;notebook_sanitize path=%s action=%s reason=%s&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| notebook_sanitize.py | 51 | <code>&#x27;missing_evidence&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| notebook_sanitize.py | 52 | <code>&#x27;evidence&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| notebook_sanitize.py | 53 | <code>&#x27;loc&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| notebook_sanitize.py | 54 | <code>&#x27;invalid_value&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| notebook_sanitize.py | 60 | <code>&#x27;expected object&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| notebook_sanitize.py | 65 | <code>&#x27;&lt;unknown&gt;&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| notebook_sanitize.py | 65 | <code>&#x27;[A-Za-z_][A-Za-z_0-9]{0,63}&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| notebook_sanitize.py | 66 | <code>&#x27;.&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| notebook_sanitize.py | 67 | <code>&#x27;dropped_unknown_field&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| notebook_sanitize.py | 69 | <code>&#x27;.&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| notebook_sanitize.py | 70 | <code>&#x27;coach&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| notebook_sanitize.py | 72 | <code>&#x27;coach_deferred&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| notebook_sanitize.py | 72 | <code>&#x27;repaired&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| notebook_sanitize.py | 80 | <code>&#x27;dropped_field&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| notebook_sanitize.py | 80 | <code>&#x27;invalid_list&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| notebook_sanitize.py | 82 | <code>0</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| notebook_sanitize.py | 86 | <code>&#x27;[&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| notebook_sanitize.py | 86 | <code>&#x27;]&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| notebook_sanitize.py | 92 | <code>&#x27;invalid_value&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| notebook_sanitize.py | 93 | <code>&#x27;dropped_entry&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| notebook_sanitize.py | 101 | <code>&#x27;invalid_value&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| notebook_sanitize.py | 104 | <code>&#x27;repaired&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| notebook_sanitize.py | 106 | <code>&#x27;dropped_field&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| notebook_sanitize.py | 112 | <code>&#x27;&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| notebook_schema.py | 1 | <code>&#x27;Typed private notebook contract from COUNSELOR_V3_PROMPTS.md section 0.&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 9 | <code>&#x27;forbid&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 12 | <code>&#x27;family&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 12 | <code>&#x27;friend&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 12 | <code>&#x27;need&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 12 | <code>&#x27;own_experience&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 12 | <code>&#x27;reels&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 12 | <code>&#x27;relative&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 12 | <code>&#x27;unknown&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 16 | <code>1</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 17 | <code>&#x27;unknown&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 18 | <code>1</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 22 | <code>&#x27;&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 23 | <code>&#x27;&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 24 | <code>&#x27;&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 28 | <code>1</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 29 | <code>1</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 30 | <code>&#x27;claimed&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 30 | <code>&#x27;proven&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 30 | <code>&#x27;sustained&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 30 | <code>&#x27;tried&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 31 | <code>1</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 32 | <code>&#x27;unknown&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 35 | <code>&#x27;evidence&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 39 | <code>&#x27;evidence is required&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 44 | <code>1</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 45 | <code>1</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 46 | <code>&#x27;high&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 46 | <code>&#x27;low&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 46 | <code>&#x27;medium&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 48 | <code>&#x27;evidence&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 52 | <code>&#x27;evidence is required&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 57 | <code>1</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 58 | <code>1</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 59 | <code>1</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 61 | <code>&#x27;evidence&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 65 | <code>&#x27;evidence is required&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 70 | <code>&#x27;&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 71 | <code>&#x27;&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 77 | <code>&#x27;&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 78 | <code>&#x27;&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 82 | <code>1</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 83 | <code>1</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 88 | <code>1</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 89 | <code>&#x27;open&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 89 | <code>&#x27;rejected&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 89 | <code>&#x27;supported&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 90 | <code>&#x27;&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 91 | <code>&#x27;&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 93 | <code>&#x27;evidence_against&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 93 | <code>&#x27;evidence_for&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 98 | <code>&#x27;after&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 101 | <code>&#x27;hypothesis evidence is required&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 106 | <code>1</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 107 | <code>1</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 108 | <code>1</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 123 | <code>1</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 124 | <code>&#x27;unknown&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 125 | <code>1</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 138 | <code>&#x27;&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 139 | <code>&#x27;&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 140 | <code>&#x27;&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 146 | <code>&#x27;decided&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 146 | <code>&#x27;goal_switcher&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 146 | <code>&#x27;impatient&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 146 | <code>&#x27;open&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 146 | <code>&#x27;open&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 146 | <code>&#x27;parent_proxy&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 146 | <code>&#x27;short_answers&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 146 | <code>&#x27;task_seeker&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 147 | <code>&#x27;focused&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 147 | <code>&#x27;full&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 147 | <code>&#x27;full&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 147 | <code>&#x27;light&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 148 | <code>&#x27;coach&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 148 | <code>&#x27;discovery&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 148 | <code>&#x27;discovery&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 148 | <code>&#x27;next_chapter&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| notebook_schema.py | 152 | <code>&#x27;coach&#x27;</code> | Notebook schema field, enum, validator, or safe default; no student-topic matching. |
| polish.py | 1 | <code>&#x27;Generic punctuation, layout and configured Unicode script checks.&#x27;</code> | Unicode property check, punctuation/layout rule, regex syntax, or error message; no topic or language word list. |
| polish.py | 10 | <code>&#x27;(?m)^\\s*(?:[-*\\u2022]&#124;\\d+[.)])\\s+&#x27;</code> | Unicode property check, punctuation/layout rule, regex syntax, or error message; no topic or language word list. |
| polish.py | 15 | <code>&#x27;&#x27;</code> | Unicode property check, punctuation/layout rule, regex syntax, or error message; no topic or language word list. |
| polish.py | 15 | <code>&#x27;QUESTION MARK&#x27;</code> | Unicode property check, punctuation/layout rule, regex syntax, or error message; no topic or language word list. |
| polish.py | 26 | <code>64</code> | Unicode property check, punctuation/layout rule, regex syntax, or error message; no topic or language word list. |
| polish.py | 28 | <code>&#x27;[A-Za-z_][A-Za-z_ ]*&#x27;</code> | Unicode property check, punctuation/layout rule, regex syntax, or error message; no topic or language word list. |
| polish.py | 29 | <code>&#x27;invalid blocked Unicode script name&#x27;</code> | Unicode property check, punctuation/layout rule, regex syntax, or error message; no topic or language word list. |
| polish.py | 31 | <code>&#x27;\\p{Script=&#x27;</code> | Unicode property check, punctuation/layout rule, regex syntax, or error message; no topic or language word list. |
| polish.py | 31 | <code>&#x27;}&#x27;</code> | Unicode property check, punctuation/layout rule, regex syntax, or error message; no topic or language word list. |
| polish.py | 33 | <code>&#x27;unknown blocked Unicode script name&#x27;</code> | Unicode property check, punctuation/layout rule, regex syntax, or error message; no topic or language word list. |
| polish.py | 38 | <code>&#x27;,&#x27;</code> | Unicode property check, punctuation/layout rule, regex syntax, or error message; no topic or language word list. |
| polish.py | 42 | <code>&#x27;Drop later questions and their trailing text without rewriting prose.&#x27;</code> | Unicode property check, punctuation/layout rule, regex syntax, or error message; no topic or language word list. |
| polish.py | 44 | <code>0</code> | Unicode property check, punctuation/layout rule, regex syntax, or error message; no topic or language word list. |
| polish.py | 44 | <code>1</code> | Unicode property check, punctuation/layout rule, regex syntax, or error message; no topic or language word list. |
| polish.py | 44 | <code>1</code> | Unicode property check, punctuation/layout rule, regex syntax, or error message; no topic or language word list. |
| prompts.py | 1 | <code>&#x27;Load the versioned Counselor prompts without embedding prompt text in code.&#x27;</code> | Prompt resource name or path; no student-topic matching. |
| prompts.py | 7 | <code>&#x27;prompts&#x27;</code> | Prompt resource name or path; no student-topic matching. |
| prompts.py | 8 | <code>&#x27;analyst&#x27;</code> | Prompt resource name or path; no student-topic matching. |
| prompts.py | 8 | <code>&#x27;counselor&#x27;</code> | Prompt resource name or path; no student-topic matching. |
| prompts.py | 8 | <code>&#x27;language_retry&#x27;</code> | Prompt resource name or path; no student-topic matching. |
| prompts.py | 8 | <code>&#x27;mirror&#x27;</code> | Prompt resource name or path; no student-topic matching. |
| prompts.py | 8 | <code>&#x27;roadmap_builder&#x27;</code> | Prompt resource name or path; no student-topic matching. |
| prompts.py | 8 | <code>&#x27;sensitive_check&#x27;</code> | Prompt resource name or path; no student-topic matching. |
| prompts.py | 14 | <code>&#x27;Unknown Counselor prompt: &#x27;</code> | Prompt resource name or path; no student-topic matching. |
| prompts.py | 15 | <code>&#x27;.md&#x27;</code> | Prompt resource name or path; no student-topic matching. |
| prompts.py | 15 | <code>&#x27;utf-8&#x27;</code> | Prompt resource name or path; no student-topic matching. |
| sensitive.py | 1 | <code>&#x27;Deferred background check for changed notebook entries.\n\nThe Analyst will call this before NotebookService.apply in PR 4. Storage does\nnot invoke a model or make content judgments on its own.\n&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| sensitive.py | 30 | <code>&#x27;sensitive_content&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| sensitive.py | 34 | <code>&#x27;One small model call for one changed entry; fail if the answer is unusable.&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| sensitive.py | 37 | <code>&#x27;content&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| sensitive.py | 37 | <code>&#x27;role&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| sensitive.py | 37 | <code>&#x27;user&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| sensitive.py | 38 | <code>&#x27;sensitive_check&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| sensitive.py | 39 | <code>&#x27;json_object&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| sensitive.py | 39 | <code>&#x27;type&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| sensitive.py | 47 | <code>&#x27;sensitive check returned invalid JSON&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| sensitive.py | 48 | <code>&#x27;sensitive&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| sensitive.py | 49 | <code>&#x27;sensitive check returned invalid decision&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| sensitive.py | 50 | <code>&#x27;sensitive&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| sensitive.py | 54 | <code>&#x27;,&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| sensitive.py | 54 | <code>&#x27;:&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| sensitive.py | 64 | <code>&#x27;id&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| sensitive.py | 66 | <code>&#x27;id&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| sensitive.py | 66 | <code>&#x27;id&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| sensitive.py | 84 | <code>&#x27;Check only changed free-text entries; never partially save on check failure.&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| sensitive.py | 94 | <code>&#x27;.&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| sensitive.py | 101 | <code>&#x27;[&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| sensitive.py | 101 | <code>&#x27;]&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| sensitive.py | 103 | <code>&#x27;notebook_sensitive path=%s reason=sensitive_content&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| sensitive.py | 113 | <code>&#x27;notebook_sensitive path=%s reason=sensitive_content&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| sensitive.py | 120 | <code>&#x27;json&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| sensitive.py | 120 | <code>&#x27;json&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| sensitive.py | 121 | <code>&#x27;&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| sensitive.py | 123 | <code>&#x27;sensitive check could not clean notebook&#x27;</code> | Module documentation, schema, or typed protocol; no student-topic matching. |
| turn.py | 1 | <code>&#x27;One fast Counselor model call, with a single language-repair exception.&#x27;</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 34 | <code>&#x27;reply&#x27;</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 36 | <code>&#x27;action&#x27;</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 37 | <code>&#x27;none&#x27;</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 37 | <code>&#x27;reply&#x27;</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 37 | <code>&#x27;type&#x27;</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 42 | <code>&#x27;&#x27;</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 42 | <code>&#x27;^\\s*```(?:json)?\\s*&#124;\\s*```\\s*$&#x27;</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 48 | <code>&#x27;[&#x27;</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 48 | <code>&#x27;```&#x27;</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 48 | <code>&#x27;{&#x27;</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 49 | <code>&#x27;none&#x27;</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 49 | <code>&#x27;type&#x27;</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 50 | <code>&#x27;&quot;&#x27;</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 53 | <code>&#x27;,&#x27;</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 54 | <code>&#x27;none&#x27;</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 54 | <code>&#x27;type&#x27;</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 57 | <code>&#x27;none&#x27;</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 57 | <code>&#x27;type&#x27;</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 60 | <code>&#x27;&#x27;</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 60 | <code>&#x27;\\\\&quot;\\s*,?\\s*$&#x27;</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 60 | <code>&#x27;none&#x27;</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 60 | <code>&#x27;type&#x27;</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 65 | <code>&#x27;&#x27;</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 65 | <code>&#x27;human:&#x27;</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 65 | <code>&#x27;human:&#x27;</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 66 | <code>&#x27;content&#x27;</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 66 | <code>&#x27;content&#x27;</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 66 | <code>&#x27;role&#x27;</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 66 | <code>&#x27;role&#x27;</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 69 | <code>&#x27;I attached a document.&#x27;</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 70 | <code>&#x27;content&#x27;</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 70 | <code>&#x27;role&#x27;</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 70 | <code>&#x27;user&#x27;</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 73 | <code>&#x27;\n\n&#x27;</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 73 | <code>&#x27;counselor&#x27;</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 78 | <code>&#x27;json_object&#x27;</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 78 | <code>&#x27;type&#x27;</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 82 | <code>1000</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 87 | <code>1000</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 91 | <code>&#x27;\n\n&#x27;</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 91 | <code>&#x27;language_retry&#x27;</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 92 | <code>&#x27;json_object&#x27;</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 92 | <code>&#x27;type&#x27;</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 96 | <code>1000</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 101 | <code>&#x27;none&#x27;</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 101 | <code>&#x27;type&#x27;</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 103 | <code>0</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 105 | <code>&#x27;none&#x27;</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 105 | <code>&#x27;type&#x27;</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn.py | 107 | <code>1000</code> | Model response protocol, history role, generic fallback handling, or timing; no student-topic matching. |
| turn_input.py | 1 | <code>&#x27;Channel-neutral student turns and causally ordered Counselor history.&#x27;</code> | Event/history protocol, role, or bounded query; no student-topic matching. |
| turn_input.py | 24 | <code>24</code> | Event/history protocol, role, or bounded query; no student-topic matching. |
| turn_input.py | 25 | <code>&#x27;Student and PAI chat across channels in this workspace, causally prior.&#x27;</code> | Event/history protocol, role, or bounded query; no student-topic matching. |
| turn_input.py | 28 | <code>&#x27;workspace.message.posted&#x27;</code> | Event/history protocol, role, or bounded query; no student-topic matching. |
| turn_input.py | 29 | <code>&#x27;human:&#x27;</code> | Event/history protocol, role, or bounded query; no student-topic matching. |
| turn_input.py | 29 | <code>&#x27;openagents:pai&#x27;</code> | Event/history protocol, role, or bounded query; no student-topic matching. |
| turn_input.py | 36 | <code>3</code> | Event/history protocol, role, or bounded query; no student-topic matching. |
| turn_input.py | 40 | <code>&#x27;content&#x27;</code> | Event/history protocol, role, or bounded query; no student-topic matching. |
| turn_input.py | 41 | <code>&#x27;chat&#x27;</code> | Event/history protocol, role, or bounded query; no student-topic matching. |
| turn_input.py | 41 | <code>&#x27;chat&#x27;</code> | Event/history protocol, role, or bounded query; no student-topic matching. |
| turn_input.py | 41 | <code>&#x27;message_type&#x27;</code> | Event/history protocol, role, or bounded query; no student-topic matching. |
| turn_input.py | 42 | <code>&#x27;[Error]&#x27;</code> | Event/history protocol, role, or bounded query; no student-topic matching. |
| turn_input.py | 44 | <code>&#x27;assistant&#x27;</code> | Event/history protocol, role, or bounded query; no student-topic matching. |
| turn_input.py | 44 | <code>&#x27;openagents:pai&#x27;</code> | Event/history protocol, role, or bounded query; no student-topic matching. |
| turn_input.py | 44 | <code>&#x27;role&#x27;</code> | Event/history protocol, role, or bounded query; no student-topic matching. |
| turn_input.py | 44 | <code>&#x27;user&#x27;</code> | Event/history protocol, role, or bounded query; no student-topic matching. |
| turn_input.py | 45 | <code>&#x27;content&#x27;</code> | Event/history protocol, role, or bounded query; no student-topic matching. |
| turn_input.py | 45 | <code>&#x27;target&#x27;</code> | Event/history protocol, role, or bounded query; no student-topic matching. |
| turn_input.py | 45 | <code>1500</code> | Event/history protocol, role, or bounded query; no student-topic matching. |
| turn_input.py | 46 | <code>&#x27;session_id&#x27;</code> | Event/history protocol, role, or bounded query; no student-topic matching. |
| turn_input.py | 46 | <code>&#x27;voice_session_id&#x27;</code> | Event/history protocol, role, or bounded query; no student-topic matching. |
| turn_input.py | 47 | <code>&#x27;session_id&#x27;</code> | Event/history protocol, role, or bounded query; no student-topic matching. |
| turn_input.py | 55 | <code>&#x27;role&#x27;</code> | Event/history protocol, role, or bounded query; no student-topic matching. |
| turn_input.py | 55 | <code>&#x27;user&#x27;</code> | Event/history protocol, role, or bounded query; no student-topic matching. |
| turn_input.py | 58 | <code>&#x27;target&#x27;</code> | Event/history protocol, role, or bounded query; no student-topic matching. |
| turn_input.py | 58 | <code>1</code> | Event/history protocol, role, or bounded query; no student-topic matching. |
| turn_input.py | 59 | <code>&#x27;session_id&#x27;</code> | Event/history protocol, role, or bounded query; no student-topic matching. |
| turn_input.py | 59 | <code>1</code> | Event/history protocol, role, or bounded query; no student-topic matching. |
| turn_input.py | 60 | <code>&#x27;session_id&#x27;</code> | Event/history protocol, role, or bounded query; no student-topic matching. |
| turn_input.py | 60 | <code>1</code> | Event/history protocol, role, or bounded query; no student-topic matching. |
