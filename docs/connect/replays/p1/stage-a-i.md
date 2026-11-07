# Stage A-I replay, connection off and on (P1-T10 Task C2)

Recorded model outputs, no network, no API key, fictional students. For each stage the workspace state of that stage is seeded, one or two recorded Counsellor turns run, and every model call's input and output is compared after masking ids, times and fact values. Screens are compared by shape (keys and types).

| Student | Stage | Model calls | Replies and inputs identical | Differences | Screen keys the connection adds |
| --- | --- | ---: | --- | ---: | --- |
| germany_master | A | 3 | yes | 0 | none |
| germany_master | B | 6 | yes | 0 | none |
| germany_master | C | 3 | yes | 0 | none |
| germany_master | D | 6 | yes | 0 | none |
| germany_master | E | 3 | yes | 0 | none |
| germany_master | F | 3 | yes | 0 | none |
| germany_master | G | 3 | yes | 0 | none |
| germany_master | H | 3 | yes | 0 | none |
| germany_master | I | 3 | yes | 0 | choose_response.choice, choose_response.plan, decision_record.plan, decision_record.steps[].due_at, decision_record.steps[].due_tz, decision_record.steps[].estimated, decision_record.steps[].owner, decision_record.steps[].provisional, decision_record.steps[].title, roadmap.chosen.choice, roadmap.chosen.plan, roadmap.chosen.steps[].due_at, roadmap.chosen.steps[].due_tz, roadmap.chosen.steps[].estimated, roadmap.chosen.steps[].owner, roadmap.chosen.steps[].provisional, roadmap.chosen.steps[].title |
| pk_bs | A | 3 | yes | 0 | none |
| pk_bs | B | 6 | yes | 0 | none |
| pk_bs | C | 3 | yes | 0 | none |
| pk_bs | D | 6 | yes | 0 | none |
| pk_bs | E | 3 | yes | 0 | none |
| pk_bs | F | 3 | yes | 0 | none |
| pk_bs | G | 3 | yes | 0 | none |
| pk_bs | H | 3 | yes | 0 | none |
| pk_bs | I | 3 | yes | 0 | choose_response.choice, choose_response.plan, decision_record.plan, decision_record.steps[].due_at, decision_record.steps[].due_tz, decision_record.steps[].estimated, decision_record.steps[].owner, decision_record.steps[].provisional, decision_record.steps[].title, roadmap.chosen.choice, roadmap.chosen.plan, roadmap.chosen.steps[].due_at, roadmap.chosen.steps[].due_tz, roadmap.chosen.steps[].estimated, roadmap.chosen.steps[].owner, roadmap.chosen.steps[].provisional, roadmap.chosen.steps[].title |

## What the replay cannot show

- The model outputs are recorded and hand-written: a reply difference can only come from a change in what the Counsellor reads or does, and the model inputs are compared byte for byte to catch that. A real model may still answer differently to the same input; only a live run shows that (Task C3).
- One or two turns per stage, on seeded state. It is not one conversation walking A to I.
- Stage I is screens, as master spec section 10 says: the replay checks the choose answer, the decision record and the journey, and one J turn after the choice.
- Only existing endpoints are compared. The new endpoints (choice options, places, my plan) exist only with the connection on and are covered by their own tests.
