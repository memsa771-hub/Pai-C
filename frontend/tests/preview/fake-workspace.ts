const noop=()=>{};
const data={token:null,workspace:{id:'student',name:'My workspace',slug:'student'},currentUser:{id:'student',name:'Sam Taylor',isAuthenticated:true},
  currentSessionId:'pai-counselor',agents:[{agentName:'pai',displayName:'PAI Counselor',status:'online',builtin:true}],
  sessions:[{sessionId:'pai-counselor',title:'PAI Counselor',status:'active',participants:['pai']}],
  files:[],browserTabs:[],browserContexts:[],pendingUploads:[],notifications:[],unreadNotificationCount:0,onlineUsers:[],
  activeSessionIds:new Set(),stoppingSessionIds:new Set(),completedSessionIds:new Set(),pendingFolderPaths:new Map(),
  currentFilePath:'',selectedFileId:null,trashEntries:[],agentModes:{},loading:false,
  consumeSkipFocus:()=>false};
const workspace=new Proxy(data,{get:(target,key)=>key in target?target[key as keyof typeof target]:noop});
export const useWorkspace=()=>workspace as any;
