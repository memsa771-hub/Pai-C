import {picture,cards,possibilities,pathResult,programs} from '../fixtures/counselor';
export const calls:{method:string;args:unknown[]}[]=[];
export const mirror={type:'mirror',version:1,status:'awaiting_confirmation',mirror:{
  intro:'Here is the picture I have so far.',confidence:'focused',
  core_picture:Object.fromEntries(Object.entries(picture.picture!).map(([key,line])=>[key,{text:line.text,evidence:'Your own words in this conversation.',unknown:false}])),
  dimensions:[{key:'strengths',name:'Practical curiosity',picture:'You try things, notice what happens and try again.',evidence:'I fixed a broken lamp with my friend.',unknown:false}],
  blockers:['We still need to test how the study itself feels to you.'],opinion:'Practical design is worth exploring alongside computing.',question:'What feels right, and what should I change?',roadmap_lanes:[]}};
let searched=false, prepared=new URLSearchParams(location.search).has('roadmap'), chosen=new URLSearchParams(location.search).has('family');
const roadmap={id:'roadmap-one',journey_id:'journey-one',goal_id:null,title:'Practical design',origin:'stated_goal',route:{},
  fit_level:'partial',fit_dimensions:{},gaps:[],steps:[{action:'Try a small project'}],total_cost:null,time_to_start:null,risks:['Test the daily study before deciding.'],scholarships:[],sources:[],generation_status:'ready',stale_reason:null,execution_run_id:'offline',version:1,favorite:false,exploring:true,dismissed_at:null,chosen_at:null,focused_at:null,created_at:'2026-10-18T12:00:00Z',updated_at:'2026-10-18T12:00:00Z'};
const api={getCounselorWorkspace:async()=>picture,getProfileCards:async()=>({cards}),getPossibilities:async()=>possibilities,
  getFamilyTalk:async()=>({ready:true,path_id:'path-one',path:'Practical design',message:'Prepare around what you know, without assuming that a concern has been resolved.',family:[{id:'person-one',role:'Parent',wish:'A dependable career',worry:'Whether the work will be stable',evidence:'My parent wants me to have dependable work.'}],evidence:[{id:'quote-one',quote:'I fixed a broken lamp with my friend.'}]}),
  prepareFamilyTalk:async()=>({event_id:'offline-family',script:'I understand that dependable work matters to you. I want to explore practical design. I fixed a broken lamp with my friend. I would like us to look at the evidence together before deciding.'}),
  acceptPathActivity:async()=>({scheduled:true}),
  getCounselorHealth:async()=>({planner_lag_alert:false}),getPath:async()=>pathResult,
  getPrograms:async()=>searched?programs:{status:'not_started',programs:[],missing:[]},
  searchPrograms:async()=>{searched=true;return{};},preparePathRoadmap:async()=>{prepared=true;return {run_id:'offline'};},
  getRoadmapChoiceToken:async()=>'offline-confirmation',chooseRoadmap:async()=>{chosen=true;return {...roadmap,chosen_at:'2026-10-18T12:01:00Z'};},
  getCounselorSummary:async()=>new URLSearchParams(location.search).has('mirror')?mirror:{type:null,status:null,version:null},
  getRoadmaps:async()=>prepared?[{...roadmap,chosen_at:chosen?'2026-10-18T12:01:00Z':null}]:[],getStudentRequests:async()=>[],getCurrentDecision:async()=>chosen?{real_objective:'A path I can test in practice.'}:null,
  getCounselorRequests:async()=>[],getCounselorResearchStatus:async()=>null,getOperatorRun:async()=>null,
  loadMessageHistory:async()=>({events:[]}),pollMessages:async()=>({messages:[]}),editStudentProfile:async()=>({saved:true}),
  answerFactCard:async()=>({saved:true}),reviewProfileCard:async()=>({saved:true}),
  submitOnboarding:async()=>({completed:true,rejected:{},saved:[]}),
};
export const workspaceApi=new Proxy(api,{get:(target,key)=>{const method=String(key);return (...args:unknown[])=>{calls.push({method,args});const fn=target[key as keyof typeof target];return fn?fn():Promise.resolve([]);};}}) as any;
(window as any).__offlineCalls=calls;
