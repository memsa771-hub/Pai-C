// @vitest-environment jsdom
import {it, expect, vi, afterEach} from 'vitest';
import {render, screen, fireEvent, waitFor, cleanup} from '@testing-library/react';
import {ConversationCard} from './inline-card';
import {workspaceApi} from '@/lib/api';
vi.mock('@/lib/workspace-context',()=>({useWorkspace:()=>({currentUser:{id:'student',name:'Student'}})}));
vi.mock('@/lib/api',()=>({workspaceApi:{sendMessage:vi.fn()}}));
afterEach(()=>{cleanup();vi.clearAllMocks();});
it('renders the first picture without inventing content',()=>{
 render(<ConversationCard channel='pai-counselor' card={{kind:'first_picture'}}>Their evidence</ConversationCard>);
 expect(screen.getByRole('heading',{name:'My first picture of you'})).toBeTruthy();
 expect(screen.getByText('Their evidence')).toBeTruthy();expect(workspaceApi.sendMessage).not.toHaveBeenCalled();
});
it('rating is an explicit student message, with zero valid and no direct map write',async()=>{
 render(<ConversationCard channel='pai-counselor' card={{kind:'rating',min:0,max:10}}>How certain?</ConversationCard>);
 const send=screen.getByRole('button',{name:'Send my rating'});expect((send as HTMLButtonElement).disabled).toBe(true);
 fireEvent.click(screen.getByRole('button',{name:'0',exact:true}));expect(workspaceApi.sendMessage).not.toHaveBeenCalled();fireEvent.click(send);
 await waitFor(()=>expect(workspaceApi.sendMessage).toHaveBeenCalledExactlyOnceWith('pai-counselor','My certainty about my direction is 0 out of 10.','Student',undefined,undefined,'student'));
 expect(await screen.findByRole('status')).toBeTruthy();
});
it('preserves a failed rating for retry',async()=>{
 vi.mocked(workspaceApi.sendMessage).mockRejectedValue(new Error());
 render(<ConversationCard channel='pai-counselor' card={{kind:'rating',min:0,max:10}}>How certain?</ConversationCard>);
 fireEvent.click(screen.getByRole('button',{name:'4',exact:true}));fireEvent.click(screen.getByRole('button',{name:'Send my rating'}));
 expect(await screen.findByRole('alert')).toBeTruthy();expect(screen.getByRole('button',{name:'4',exact:true}).getAttribute('aria-pressed')).toBe('true');
});
