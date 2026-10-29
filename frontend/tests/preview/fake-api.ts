import {picture,vault,vaultCatalog,possibilities,pathResult,programs,roadmapPage,chosenRoute,mirrorCard,mirrorEmpty,adminUsage} from '../fixtures/counselor';
import type {ChosenRoute} from '@/lib/roadmap';
export const calls:{method:string;args:unknown[]}[]=[];
// ?mirror=empty: the Mirror before it is ready (onboarding only).
const mirrorState=new URLSearchParams(location.search).get('mirror')==='empty'?mirrorEmpty:mirrorCard;
const sampleSource=(path:string)=>({source_url:`https://example.org/${path}`,checked_at:'2026-10-10T09:00:00Z',status:'verified'});
// Same shape as the backend payload: fees and rules are sourced facts;
// eligibility follows eligibility(): unconfirmed means unknown, a band needs
// every rule met, and a route only appears with gaps.
const fact=(path:string,value:unknown,status='verified')=>({value,...sampleSource(path),status,fact_id:`offline:${path}`});
const richPrograms={status:'completed',missing:[],programs:[
  {opportunity_id:'program-one',title:'Design foundation programme, Sample Institute',...sampleSource('design-foundation'),
    rules:[fact('design-foundation/entry','Completed upper secondary education')],fees:{tuition:fact('design-foundation/fees','1,200 USD per year')},
    eligibility:{label:'realistic',gaps:[{field:'qualification',status:'met'}],route:[]}},
  {opportunity_id:'program-two',title:'Applied product design, Example College',...sampleSource('applied-design'),status:'unconfirmed',
    rules:[],fees:{},eligibility:{label:'unknown',gaps:[],route:[]}},
  {opportunity_id:'program-three',title:'Creative technology diploma, Demo Polytechnic',...sampleSource('creative-technology'),
    rules:[fact('creative-technology/entry','A portfolio of three small projects')],fees:{},
    eligibility:{label:'not_yet',gaps:[{field:'portfolio',status:'fixable',remediation:{action:'Take a short portfolio course first'}}],
      route:[{action:'Take a short portfolio course first',...sampleSource('portfolio-course')}]}},
]};
let searched=new URLSearchParams(location.search).has('programs');
// The Roadmap page (GET /v1/roadmap): ?chosen=1 starts with a chosen route.
let route:ChosenRoute|null=new URLSearchParams(location.search).has('chosen')?structuredClone(chosenRoute):null;
const choose=(fieldKey:string)=>{const card=roadmapPage.fields.find(c=>c.field_key===fieldKey)!;
  const steps=structuredClone(card.steps||[]);
  route={id:'route-offline',field_key:fieldKey,possibility_id:card.possibility_id,title:card.title,chosen_at:'2026-10-26T09:00:00Z',
    steps,time:card.time,snapshot_steps:steps.map(({key,label_key,values,status})=>({key,label_key,values,status})),
    steps_done:[],snapshot_verdict:card.verdict,live_status:card.status};return route;};
// A tick makes a step done with "You marked it" when no Vault entry is behind it, as the backend does.
const tick=(key:string,done:boolean)=>{const r=route!;r.steps_done=done?[...r.steps_done.filter(k=>k!==key),key]:r.steps_done.filter(k=>k!==key);
  r.steps=r.steps.map(s=>s.key!==key?s:{...s,manual_done:done,status:done?'done':'not',
    evidence:done?(s.evidence||{id:null,level:'stated',source_label:'You marked it'}):(s.evidence?.id?s.evidence:null)});return structuredClone(r);};
const api={getCounselorWorkspace:async()=>picture,getVault:async()=>vault,getVaultCatalog:async()=>vaultCatalog,getPossibilities:async()=>possibilities,
  getFamilyTalk:async()=>({ready:true,path_id:'path-one',path:'Practical design',message:'Prepare around what you know, without assuming that a concern has been resolved.',family:[{id:'person-one',role:'Parent',wish:'A dependable career',worry:'Whether the work will be stable',evidence:'My parent wants me to have dependable work.'}],evidence:[{id:'quote-one',quote:'I fixed a broken lamp with my friend.'}]}),
  prepareFamilyTalk:async()=>({event_id:'offline-family',script:'I understand that dependable work matters to you. I want to explore practical design. I fixed a broken lamp with my friend. I would like us to look at the evidence together before deciding.'}),
  acceptPathActivity:async()=>({scheduled:true}),
  addOwnPath:async()=>({...possibilities[1],id:'own-path',title:'Nursing',why:'Nursing',source:'student',status:'saved',fit:[]}),
  
  getRoadmapPage:async()=>({...roadmapPage,chosen:route&&structuredClone(route)}),
  chooseRoute:async(fieldKey:string)=>choose(fieldKey),
  setRouteStep:async(key:string,done:boolean)=>tick(key,done),
  withdrawRoute:async()=>{const old=route;route=null;return old;},
  getCounselorHealth:async()=>({planner_lag_alert:false}),getPath:async()=>pathResult,
  // The preview signs in as a founder, so Settings shows the spend card.
  getAdminUsage:async()=>structuredClone(adminUsage),
  getPrograms:async()=>searched?(new URLSearchParams(location.search).has('programs')?richPrograms:programs):{status:'not_started',programs:[],missing:[]},
  searchPrograms:async()=>{searched=true;return{};},
  getMirror:async()=>structuredClone(mirrorState),
  getStudentRequests:async()=>[],
  getCounselorRequests:async()=>[],getOperatorRun:async()=>null,
  loadMessageHistory:async()=>({events:[]}),pollMessages:async()=>({messages:[]}),
  answerFactCard:async()=>({saved:true}),
  addVaultEntry:async()=>({saved:true}),editVaultEntry:async()=>({saved:true}),confirmVaultEntry:async()=>({saved:true}),removeVaultEntry:async()=>({saved:true}),resolveVaultConflict:async()=>({resolved:true}),
  submitOnboarding:async()=>({completed:true,rejected:{},saved:[]}),
  listShares:async()=>[{id:'share-1',workspaceId:'offline',channelName:'pai-counselor',title:'My conversation with PAI',shareToken:'offline-token',messageCount:12,status:'active',createdAt:'2026-10-18T09:00:00Z'}],
};
// ?state=loading|error|empty forces every read into that state for review.
const forced=new URLSearchParams(location.search).get('state');
const emptyReads:Record<string,unknown>={
  getCounselorWorkspace:{coverage:Object.fromEntries(Object.keys(picture.coverage).map(k=>[k,{covered:false,item_count:0,evidence:null}])),
    personal:{world:{},self:[],source:[],pressures:{items:[]},sure:{score:null,history:[]}},capabilities:[],academic:{records:{}},sections:{},
    picture:{header:{name:null,education_line:null},unknowns:[],text:null,ready:false,version:'v0'},moments:{},ratings:[]},
  getVault:{details:{},story:[],conflicts:[],stale:[]},getPossibilities:[],getRoadmapPage:{education_line:null,counts:{open:0,step:0,not_open:0,unknown:0},fields:[],chosen:null},getMirror:{...mirrorEmpty,header:{name:null,education_line:null},areas:mirrorEmpty.areas.map(a=>({...a,level:0,entries:[]})),
    unknowns:mirrorCard.areas.map((a,i)=>({area:a.key,label:a.label,question_key:`topic_text.${a.key}`,priority:i+1}))},
};
const read=(method:string)=>method.startsWith('get')&&method!=='getCounselorHealth'&&method!=='getFileUrl';
export const workspaceApi=new Proxy(api,{get:(target,key)=>{const method=String(key);return (...args:unknown[])=>{calls.push({method,args});
  if(forced&&read(method)){
    if(forced==='loading') return new Promise(()=>{});
    if(forced==='error') return Promise.reject(new Error('Offline review: forced error'));
    if(forced==='empty'&&method in emptyReads) return Promise.resolve(structuredClone(emptyReads[method]));
  }
  const fn=target[key as keyof typeof target] as ((...a:unknown[])=>Promise<unknown>)|undefined;return fn?fn(...args):Promise.resolve([]);};}}) as any;
(window as any).__offlineCalls=calls;
