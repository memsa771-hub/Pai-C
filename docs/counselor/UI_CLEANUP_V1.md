# Deferred UI cleanup

The Counselor-only shell landed in e361e7e. The approved deferred UI group now has no external importers. Shared ListPanel remains with Files and Browser branches. No shared services, API methods, models, tables or tests were deleted.

| File | Lines | Evidence before deletion |
| --- | ---: | --- |
| `frontend/components/monitor/monitor-grid.tsx` | 327 | `rg -n --fixed-strings monitor-grid frontend --glob *.ts --glob *.tsx`: frontend\components\monitor\monitor-tile.tsx:21:import type { TileData } from './monitor-grid';; matches are entirely within this removed group. |
| `frontend/components/monitor/monitor-overlay.tsx` | 268 | `rg -n --fixed-strings monitor-overlay frontend --glob *.ts --glob *.tsx`: frontend\components\monitor\monitor-grid.tsx:10:import { MonitorOverlay } from './monitor-overlay';; matches are entirely within this removed group. |
| `frontend/components/monitor/monitor-tile.tsx` | 220 | `rg -n --fixed-strings monitor-tile frontend --glob *.ts --glob *.tsx`: frontend\components\monitor\monitor-grid.tsx:9:import { MonitorTile } from './monitor-tile';; matches are entirely within this removed group. |
| `frontend/components/agents/agent-profile-panel.tsx` | 224 | `rg -n --fixed-strings agent-profile-panel frontend --glob *.ts --glob *.tsx`: no matches; matches are entirely within this removed group. |
| `frontend/components/threads/thread-list.tsx` | 924 | `rg -n --fixed-strings thread-list frontend --glob *.ts --glob *.tsx`: no matches; matches are entirely within this removed group. |
| `frontend/components/routines/routines-view.tsx` | 153 | `rg -n --fixed-strings routines-view frontend --glob *.ts --glob *.tsx`: no matches; matches are entirely within this removed group. |
| `frontend/components/routines/routine-list.tsx` | 161 | `rg -n --fixed-strings routine-list frontend --glob *.ts --glob *.tsx`: no matches; matches are entirely within this removed group. |
| `frontend/components/routines/use-routine-format.ts` | 68 | `rg -n --fixed-strings use-routine-format frontend --glob *.ts --glob *.tsx`: frontend\components\routines\routines-view.tsx:12:import { useRoutineFormat } from './use-routine-format';; frontend\components\routines\routine-list.tsx:16:import { useRoutineFormat } from './use-routine-format';; matches are entirely within this removed group. |
| `frontend/components/knowledge/knowledge-view.tsx` | 223 | `rg -n --fixed-strings knowledge-view frontend --glob *.ts --glob *.tsx`: no matches; matches are entirely within this removed group. |
| `frontend/components/knowledge/knowledge-list.tsx` | 242 | `rg -n --fixed-strings knowledge-list frontend --glob *.ts --glob *.tsx`: frontend\components\knowledge\knowledge-view.tsx:20: * (see knowledge-list.tsx), so this view only renders the selected entry —; matches are entirely within this removed group. |
| `frontend/components/knowledge/knowledge-editor.tsx` | 126 | `rg -n --fixed-strings knowledge-editor frontend --glob *.ts --glob *.tsx`: frontend\components\knowledge\knowledge-view.tsx:15:import { KnowledgeEditor } from './knowledge-editor';; frontend\components\knowledge\knowledge-list.tsx:16:import { KnowledgeEditor } from './knowledge-editor';; matches are entirely within this removed group. |
| `frontend/components/knowledge/knowledge-utils.ts` | 18 | `rg -n --fixed-strings knowledge-utils frontend --glob *.ts --glob *.tsx`: frontend\components\knowledge\knowledge-view.tsx:16:import { knowledgeAuthorName, stripLeadingTitle } from './knowledge-utils';; matches are entirely within this removed group. |

Kept: AppSidebar, MobileHeader, wrapper/context/API/notifications, CreateRoutineDialog, orchestration and sharing controls, integration settings and Browser backend. They are shared or still imported. No OS tool or plugin was proven safe to delete. tasks.list/tasks.create and workflow advancement remain an OS developer contract question.

Total: 12 files, 2954 file lines removed (plus six ListPanel branch/import lines).
