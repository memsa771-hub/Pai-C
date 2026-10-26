import {picture,vault,vaultCatalog,possibilities,pathResult,programs} from '../fixtures/counselor';
export const calls:{method:string;args:unknown[]}[]=[];
export const mirror={type:'mirror',version:1,status:'awaiting_confirmation',mirror:{
  intro:'Here is the picture I have so far.',confidence:'focused',
  core_picture:Object.fromEntries(Object.entries(picture.picture!).map(([key,line])=>[key,{text:line.text,evidence:'Your own words in this conversation.',unknown:false}])),
  dimensions:[{key:'strengths',name:'Practical curiosity',picture:'You try things, notice what happens and try again.',evidence:'I fixed a broken lamp with my friend.',unknown:false}],
  blockers:['We still need to test how the study itself feels to you.'],opinion:'Practical design is worth exploring alongside computing.',question:'What feels right, and what should I change?',roadmap_lanes:[]}};
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
let searched=new URLSearchParams(location.search).has('programs'), prepared=new URLSearchParams(location.search).has('roadmap'), chosen=new URLSearchParams(location.search).has('family');
const roadmap={id:'roadmap-one',journey_id:'journey-one',goal_id:null,title:'Practical design',origin:'stated_goal',route:{},
  fit_level:'partial',fit_dimensions:{},gaps:[],steps:[{action:'Try a small project'},{action:'Talk with a student on this route'},{action:'Read one course outline together with family'}],total_cost:null,time_to_start:null,risks:['Test the daily study before deciding.','Check the cost of materials.'],try_it:{kind:'taste_the_work',what:'Build a paper prototype of an everyday object and change it once.',time_needed:'About two hours',questions:['Which part did you enjoy most?']},scholarships:[],sources:[],generation_status:'ready',stale_reason:null,execution_run_id:'offline',version:1,favorite:false,exploring:true,dismissed_at:null,chosen_at:null,focused_at:null,created_at:'2026-10-18T12:00:00Z',updated_at:'2026-10-18T12:00:00Z'};
const api={getCounselorWorkspace:async()=>picture,getVault:async()=>vault,getVaultCatalog:async()=>vaultCatalog,getPossibilities:async()=>prepared?possibilities.map(p=>p.id==='path-one'?{...p,roadmap_id:'roadmap-one'}:p):possibilities,
  getFamilyTalk:async()=>({ready:true,path_id:'path-one',path:'Practical design',message:'Prepare around what you know, without assuming that a concern has been resolved.',family:[{id:'person-one',role:'Parent',wish:'A dependable career',worry:'Whether the work will be stable',evidence:'My parent wants me to have dependable work.'}],evidence:[{id:'quote-one',quote:'I fixed a broken lamp with my friend.'}]}),
  prepareFamilyTalk:async()=>({event_id:'offline-family',script:'I understand that dependable work matters to you. I want to explore practical design. I fixed a broken lamp with my friend. I would like us to look at the evidence together before deciding.'}),
  acceptPathActivity:async()=>({scheduled:true}),
  addOwnPath:async()=>({...possibilities[1],id:'own-path',title:'Nursing',why:'Nursing',source:'student',status:'saved',fit:[]}),
  
  getCounselorHealth:async()=>({planner_lag_alert:false}),getPath:async()=>pathResult,
  getPrograms:async()=>searched?(new URLSearchParams(location.search).has('programs')?richPrograms:programs):{status:'not_started',programs:[],missing:[]},
  searchPrograms:async()=>{searched=true;return{};},preparePathRoadmap:async()=>{prepared=true;return {run_id:'offline'};},
  getRoadmap:async()=>({...roadmap,chosen_at:chosen?'2026-10-18T12:01:00Z':null,evidence:null,evidence_history:[]}),
  getRoadmapChoiceToken:async()=>'offline-confirmation',chooseRoadmap:async()=>{chosen=true;return {...roadmap,chosen_at:'2026-10-18T12:01:00Z'};},
  getCounselorSummary:async()=>new URLSearchParams(location.search).has('mirror')?mirror:{type:null,status:null,version:null},
  getRoadmaps:async()=>prepared?[{...roadmap,chosen_at:chosen?'2026-10-18T12:01:00Z':null}]:[],getStudentRequests:async()=>[],getCurrentDecision:async()=>chosen?{real_objective:'A path I can test in practice.'}:null,
  getCounselorRequests:async()=>[],getCounselorResearchStatus:async()=>null,getOperatorRun:async()=>null,
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
    picture:null,mirror_status:null,moments:{},ratings:[]},
  getVault:{details:{},story:[],conflicts:[],stale:[]},getPossibilities:[],getRoadmaps:[],getCurrentDecision:null,getCounselorSummary:{type:null,status:null,version:null},
};
const read=(method:string)=>method.startsWith('get')&&method!=='getCounselorHealth'&&method!=='getFileUrl';
export const workspaceApi=new Proxy(api,{get:(target,key)=>{const method=String(key);return (...args:unknown[])=>{calls.push({method,args});
  if(forced&&read(method)){
    if(forced==='loading') return new Promise(()=>{});
    if(forced==='error') return Promise.reject(new Error('Offline review: forced error'));
    if(forced==='empty'&&method in emptyReads) return Promise.resolve(structuredClone(emptyReads[method]));
  }
  const fn=target[key as keyof typeof target];return fn?fn():Promise.resolve([]);};}}) as any;
(window as any).__offlineCalls=calls;
