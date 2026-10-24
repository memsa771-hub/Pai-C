// @vitest-environment jsdom
import {it,expect,vi,afterEach} from 'vitest';
import {render,screen,fireEvent,cleanup,waitFor,within} from '@testing-library/react';
import {CounselorSettings} from './settings';
import {workspaceApi} from '@/lib/api';
import {RecentSignInRequired,requestPasswordReset} from '@/lib/auth/service';
import {signOutAndGoToLanding} from '@/lib/auth-redirects';
const theme=vi.hoisted(()=>({setTheme:vi.fn(),theme:'light'}));
vi.mock('next-themes',()=>({useTheme:()=>theme}));
vi.mock('@/lib/api',()=>({workspaceApi:{deleteMyAccount:vi.fn(),editStudentProfile:vi.fn(),getProfileCards:vi.fn(),exportCounselorData:vi.fn(),listShares:vi.fn(),deleteShare:vi.fn()}}));
vi.mock('@/lib/auth/service',()=>({requestPasswordReset:vi.fn(),RecentSignInRequired:class extends Error{}}));
vi.mock('@/lib/auth-redirects',()=>({signOutAndReturnToSignIn:vi.fn(),signOutAndGoToLanding:vi.fn()}));
vi.mock('@/components/ui/dialogs-provider',()=>({useConfirm:()=>vi.fn().mockResolvedValue(false)}));
vi.mock('@/components/feedback/feedback-dialog',()=>({FeedbackDialog:()=><div role="dialog">feedback</div>}));
const ws=vi.hoisted(()=>({notificationSound:false,setNotificationSound:vi.fn()}));
vi.mock('@/lib/workspace-context',()=>({useWorkspace:()=>ws}));
vi.mock('@/lib/pai-auth-context',()=>({usePaiAuth:()=>({user:{displayName:'Sam',email:'sam@example.test'},signOut:vi.fn()})}));
afterEach(()=>{cleanup();vi.clearAllMocks();window.history.replaceState({},'','/');});
const open=(name:string)=>fireEvent.click(within(screen.getByRole('navigation',{name:'Settings sections'})).getByRole('button',{name}));

it('is the one settings place, in sections, with no operator controls',()=>{
  const navigate=vi.fn();
  render(<CounselorSettings onNavigate={navigate}/>);
  for (const name of ['Account','Appearance','Notifications','Privacy & data','Help']) expect(screen.getByRole('button',{name})).toBeTruthy();
  expect(screen.getByText('sam@example.test')).toBeTruthy();
  // The name lives in the profile; Settings sends the student there.
  fireEvent.click(screen.getByRole('button',{name:'Edit in About you'}));expect(navigate).toHaveBeenCalledWith('profile');
  for (const gone of [/connected channels/i,/workspace token/i,/slack|telegram|lark/i,/monitor mode/i,/reply language/i]) expect(screen.queryByText(gone)).toBeNull();
});
it('sends a password reset link to the account email',async()=>{
  vi.mocked(requestPasswordReset).mockResolvedValue(undefined);
  render(<CounselorSettings/>);
  fireEvent.click(screen.getByRole('button',{name:'Send reset link'}));
  expect(await screen.findByText('Link sent to sam@example.test.')).toBeTruthy();
  expect(requestPasswordReset).toHaveBeenCalledWith('sam@example.test');
});
it('changes theme and the notification sound locally',()=>{
  render(<CounselorSettings/>);
  open('Appearance');fireEvent.click(screen.getByRole('radio',{name:'Dark'}));expect(theme.setTheme).toHaveBeenCalledWith('dark');
  open('Notifications');fireEvent.click(screen.getByRole('switch',{name:'Sound for new messages'}));expect(ws.setNotificationSound).toHaveBeenCalledWith(true);
  expect(workspaceApi.editStudentProfile).not.toHaveBeenCalled();
});
it('lists shared links and stops sharing one',async()=>{
  vi.mocked(workspaceApi.listShares).mockResolvedValue([{id:'s1',workspaceId:'w',channelName:'pai-counselor',title:'My chat',shareToken:'tok',messageCount:3,status:'active',createdAt:'2026-10-18T00:00:00Z'}]);
  vi.mocked(workspaceApi.deleteShare).mockResolvedValue(undefined);
  render(<CounselorSettings/>);
  open('Privacy & data');
  expect(await screen.findByText('My chat')).toBeTruthy();
  fireEvent.click(screen.getByRole('button',{name:'Stop sharing'}));
  await waitFor(()=>expect(screen.queryByText('My chat')).toBeNull());
  expect(workspaceApi.deleteShare).toHaveBeenCalledWith('s1');
});
it('asks once before deleting the account and surfaces failure',async()=>{
  vi.mocked(workspaceApi.listShares).mockResolvedValue([]);
  vi.mocked(workspaceApi.deleteMyAccount).mockRejectedValue(new Error());
  render(<CounselorSettings/>);
  open('Privacy & data');
  fireEvent.click(screen.getByRole('button',{name:'Delete my account'}));
  expect(screen.getByText('This will permanently delete your account and all your data.')).toBeTruthy();
  expect(workspaceApi.deleteMyAccount).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button',{name:'Delete my account'}));
  expect(await screen.findByRole('alert')).toBeTruthy();expect(workspaceApi.deleteMyAccount).toHaveBeenCalledTimes(1);
});
it('after deleting, signs out here and goes to the landing page',async()=>{
  vi.mocked(workspaceApi.listShares).mockResolvedValue([]);
  vi.mocked(workspaceApi.deleteMyAccount).mockResolvedValue();
  render(<CounselorSettings/>);
  open('Privacy & data');
  fireEvent.click(screen.getByRole('button',{name:'Delete my account'}));
  fireEvent.click(screen.getByRole('button',{name:'Delete my account'}));
  await waitFor(()=>expect(signOutAndGoToLanding).toHaveBeenCalledTimes(1));
});
it('asks for a fresh sign-in when the last one is too old',async()=>{
  vi.mocked(workspaceApi.listShares).mockResolvedValue([]);
  vi.mocked(workspaceApi.deleteMyAccount).mockRejectedValue(new RecentSignInRequired());
  render(<CounselorSettings/>);
  open('Privacy & data');
  fireEvent.click(screen.getByRole('button',{name:'Delete my account'}));
  fireEvent.click(screen.getByRole('button',{name:'Delete my account'}));
  expect(await screen.findByText('For your safety, sign in again, then delete your account.')).toBeTruthy();
  expect(screen.getByRole('button',{name:'Sign in again'})).toBeTruthy();
});
it('exports through the owner-scoped data API and reports download failure',async()=>{
  vi.mocked(workspaceApi.listShares).mockResolvedValue([]);
  vi.mocked(workspaceApi.exportCounselorData).mockRejectedValue(new Error());
  render(<CounselorSettings/>);
  open('Privacy & data');
  fireEvent.click(screen.getByRole('button',{name:'Export my Counselor data'}));
  expect(await screen.findByRole('alert')).toBeTruthy();expect(workspaceApi.exportCounselorData).toHaveBeenCalledTimes(1);
  expect(workspaceApi.getProfileCards).not.toHaveBeenCalled();
});
it('opens feedback from Help',()=>{
  render(<CounselorSettings/>);
  open('Help');fireEvent.click(screen.getByRole('button',{name:'Write feedback'}));
  expect(screen.getByRole('dialog')).toBeTruthy();
});
