// @vitest-environment jsdom
import {it,expect,vi,afterEach} from 'vitest';
import {render,screen,fireEvent,cleanup,waitFor} from '@testing-library/react';
import {CounselorSettings} from './settings';
import {workspaceApi} from '@/lib/api';
const theme=vi.hoisted(()=>({setTheme:vi.fn(),theme:'light'}));
vi.mock('next-themes',()=>({useTheme:()=>theme}));
vi.mock('@/lib/api',()=>({workspaceApi:{deleteMyAccount:vi.fn(),editStudentProfile:vi.fn(),getProfileCards:vi.fn(),exportCounselorData:vi.fn()}}));
afterEach(()=>{cleanup();vi.clearAllMocks();});
it('changes theme locally and offers no reply-language setting',()=>{
  render(<CounselorSettings base='/student'/>);
  fireEvent.click(screen.getByRole('button',{name:'Dark',exact:true}));expect(theme.setTheme).toHaveBeenCalledWith('dark');
  expect(screen.queryByText(/reply language/i)).toBeNull();
  expect(workspaceApi.editStudentProfile).not.toHaveBeenCalled();
});
it('requires an explicit irreversible-deletion acknowledgement and surfaces failure',async()=>{
  vi.mocked(workspaceApi.deleteMyAccount).mockRejectedValue(new Error());
  render(<CounselorSettings base='/student'/>);
  fireEvent.click(screen.getByRole('button',{name:'Delete my app data',exact:true}));
  const submit=screen.getByRole('button',{name:'Permanently delete my app data'});
  expect((submit as HTMLButtonElement).disabled).toBe(true);expect(workspaceApi.deleteMyAccount).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('checkbox'));fireEvent.click(submit);
  expect(await screen.findByRole('alert')).toBeTruthy();expect(workspaceApi.deleteMyAccount).toHaveBeenCalledTimes(1);
});

it('exports through the owner-scoped data API and reports download failure',async()=>{
 vi.mocked(workspaceApi.exportCounselorData).mockRejectedValue(new Error());
 render(<CounselorSettings base='/student'/>);
 fireEvent.click(screen.getByRole('button',{name:'Export my Counselor data'}));
 expect(await screen.findByRole('alert')).toBeTruthy();expect(workspaceApi.exportCounselorData).toHaveBeenCalledTimes(1);
 expect(workspaceApi.getProfileCards).not.toHaveBeenCalled();
});
