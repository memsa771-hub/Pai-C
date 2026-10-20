// @vitest-environment jsdom
import {it,expect,vi,afterEach} from 'vitest';
import {render,screen,fireEvent,cleanup} from '@testing-library/react';
import {Journey} from './journey';
import {workspaceApi} from '@/lib/api';
import {picture} from '@/tests/fixtures/counselor';
vi.mock('@/lib/api',()=>({workspaceApi:{getCounselorWorkspace:vi.fn()}}));
afterEach(()=>{cleanup();vi.clearAllMocks();});
it('gives all A-K stages a home and links known conversation moments',async()=>{
  vi.mocked(workspaceApi.getCounselorWorkspace).mockResolvedValue(picture);
  const navigate=vi.fn();render(<Journey navigate={navigate}/>);
  await screen.findByRole('heading',{name:'Stages A to K'});
  expect(screen.getAllByRole('listitem')).toHaveLength(11);
  expect(screen.getAllByRole('listitem').filter((li)=>li.getAttribute('aria-current')==='step')).toHaveLength(1);
  // Picking a stage on the trail shows it, with its conversation moment.
  fireEvent.click(screen.getByRole('button',{name:/^Stage B: Getting to know you/}));
  await screen.findByRole('heading',{name:/Getting to know you/});
  fireEvent.click(screen.getAllByRole('button',{name:'Open conversation'}).at(-1)!);
  expect(navigate).toHaveBeenCalledWith('threads','m1');
});
it('keeps a failed load retryable',async()=>{
  vi.mocked(workspaceApi.getCounselorWorkspace).mockRejectedValueOnce(new Error());
  render(<Journey navigate={vi.fn()}/>);expect(await screen.findByRole('alert')).toBeTruthy();
  expect(screen.getByRole('button',{name:'Try again'})).toBeTruthy();
});
