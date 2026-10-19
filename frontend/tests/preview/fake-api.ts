import {picture,cards,possibilities,pathResult,programs} from '../fixtures/counselor';
export const calls:{method:string;args:unknown[]}[]=[];
export const mirror={type:'mirror',version:1,status:'awaiting_confirmation',mirror:{
  intro:'Here is the picture I have so far.',confidence:'focused',
  core_picture:Object.fromEntries(Object.entries(picture.picture!).map(([key,line])=>[key,{text:line.text,evidence:'Your own words in this conversation.',unknown:false}])),
  dimensions:[{key:'strengths',name:'Practical curiosity',picture:'You try things, notice what happens and try again.',evidence:'I fixed a broken lamp with my friend.',unknown:false}],
  blockers:['We still need to test how the study itself feels to you.'],opinion:'Practical design is worth exploring alongside computing.',question:'What feels right, and what should I change?',roadmap_lanes:[]}};
let searched=false;
const api={getCounselorWorkspace:async()=>picture,getProfileCards:async()=>({cards}),getPossibilities:async()=>possibilities,
  getCounselorHealth:async()=>({planner_lag_alert:false}),getPath:async()=>pathResult,
  getPrograms:async()=>searched?programs:{status:'not_started',programs:[],missing:[]},
  searchPrograms:async()=>{searched=true;return{};},preparePathRoadmap:async()=>({run_id:'offline'}),
  getCounselorSummary:async()=>new URLSearchParams(location.search).has('mirror')?mirror:{type:null,status:null,version:null},
  getRoadmaps:async()=>[],getStudentRequests:async()=>[],getCurrentDecision:async()=>null,
  getCounselorRequests:async()=>[],getCounselorResearchStatus:async()=>null,getOperatorRun:async()=>null,
  loadMessageHistory:async()=>({events:[]}),pollMessages:async()=>({messages:[]}),editStudentProfile:async()=>({saved:true}),
  answerFactCard:async()=>({saved:true}),reviewProfileCard:async()=>({saved:true}),
  submitOnboarding:async()=>({completed:true,rejected:{},saved:[]}),
};
export const workspaceApi=new Proxy(api,{get:(target,key)=>{const method=String(key);return (...args:unknown[])=>{calls.push({method,args});const fn=target[key as keyof typeof target];return fn?fn():Promise.resolve([]);};}}) as any;
(window as any).__offlineCalls=calls;
