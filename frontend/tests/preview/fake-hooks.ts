import type {WorkspaceMessage} from '@/lib/types';
export const messages:WorkspaceMessage[]=[
  {messageId:'m1',sessionId:'pai-counselor',senderType:'human',senderName:'Sam',content:'I enjoy making things work. I repaired a lamp with a friend, but I am not sure where that could lead.',mentions:[],targetAgents:null,messageType:'chat',metadata:{},createdAt:'2026-10-18T12:00:00Z'},
  {messageId:'m2',sessionId:'pai-counselor',senderType:'agent',senderName:'PAI Counselor',content:'You seem drawn to understanding how something works, then testing it with your hands. We can explore that without deciding your future today. What part of the repair stayed with you?',mentions:[],targetAgents:null,messageType:'chat',metadata:{},createdAt:'2026-10-18T12:01:00Z'},
];
const noop=()=>{};
const polling={messages,loading:false,forceRefresh:noop,generation:1,loadOlder:async()=>{},hasOlder:false,loadingOlder:false};
export const useMessagePolling=()=>polling;
export const useOperatorStatus=()=>null;
export const useComposingSignal=()=>({notifyFocus:noop,notifyBlur:noop,notifyTyping:noop});
