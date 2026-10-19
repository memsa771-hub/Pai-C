import type {WorkspaceMessage} from '@/lib/types';
export const messages:WorkspaceMessage[]=[
  {messageId:'m1',sessionId:'pai-counselor',senderType:'human',senderName:'Sam',content:'I enjoy making things work. I repaired a lamp with a friend, but I am not sure where that could lead.',mentions:[],targetAgents:null,messageType:'chat',metadata:{},createdAt:'2026-10-18T12:00:00Z'},
  {messageId:'m2',sessionId:'pai-counselor',senderType:'agent',senderName:'PAI Counselor',content:'You seem drawn to understanding how something works, then testing it with your hands. We can explore that without deciding your future today. What part of the repair stayed with you?',mentions:[],targetAgents:null,messageType:'chat',metadata:{},createdAt:'2026-10-18T12:01:00Z'},
];
const card=new URLSearchParams(location.search).get('card');
if(card==='picture') {messages[1].metadata={counselor_card:{kind:'first_picture'}};messages[1].content='You enjoy figuring out how parts work together, and you have tested that by repairing something. We can look at practical design and computing as possibilities. What should I correct in that picture?';}
if(card==='rating') {messages[1].metadata={counselor_card:{kind:'rating',min:0,max:10}};messages[1].content='How sure do you feel about your direction right now?';}
if(card==='fact') {messages[1].metadata={fact_card:{key:'board',label:'Awarding board',kind:'choice',choices:[{value:'Reviewed catalog entry',label:'Reviewed catalog entry'}],upload_invite:'Upload a result card',record_id:'education-one'}};messages[1].content='You can choose the awarding board or use the wording on your result card.';}
if(card==='paths') {messages[1].metadata={possibility_id:'path-one'};messages[1].content='Here is one direction worth exploring, based on what you told me.';}
if(card==='typing') messages.push({messageId:'m3',sessionId:'pai-counselor',senderType:'agent',senderName:'pai',content:'',mentions:[],targetAgents:null,messageType:'loading',metadata:{},createdAt:'2026-10-18T12:02:00Z'});
if(card==='empty') messages.splice(0,messages.length);
const noop=()=>{};
const polling={messages,loading:false,forceRefresh:noop,generation:1,loadOlder:async()=>{},hasOlder:false,loadingOlder:false};
export const useMessagePolling=()=>polling;
export const useOperatorStatus=()=>null;
export const useComposingSignal=()=>({notifyFocus:noop,notifyBlur:noop,notifyTyping:noop});
