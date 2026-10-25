import React from 'react';
import {createRoot} from 'react-dom/client';
import {ThemeProvider} from 'next-themes';
import {I18nProvider} from '@/lib/i18n';
import {DialogsProvider} from '@/components/ui/dialogs-provider';
import {LayoutProvider} from '@/components/layout/layout-context';
import {CounselorShell} from '@/components/counselor/workspace/shell';
import {OnboardingView} from '@/components/onboarding/onboarding-view';
import {KitGallery} from './kit-gallery';
import SignIn from '@/app/sign-in/page';
import SignUp from '@/app/sign-up/page';
import ForgotPassword from '@/app/forgot-password/page';
import AuthAction from '@/app/auth/action/page';
import VerifyEmail from '@/app/auth/verify-email/page';
const authPages:Record<string,()=>React.JSX.Element|null>={'/sign-in':SignIn,'/sign-up':SignUp,'/forgot-password':ForgotPassword,'/auth/action':AuthAction,'/auth/verify-email':VerifyEmail};
import '@/styles/globals.css';
// Fixture-only entry point: deliberately cannot contact the application or a provider.
window.fetch=async()=>{throw new Error('Network disabled in offline UI review');};
const q=new URLSearchParams(location.search);
const entry={required:true,completedAt:null,prefill:{currentCountry:'Pakistan'},fields:[
  {name:'firstName',fieldKey:'identity.full_name',required:true,choices:[],isDate:false,step:1},
  {name:'lastName',fieldKey:'identity.full_name',required:true,choices:[],isDate:false,step:1},
  {name:'level',fieldKey:'education',required:true,choices:['matric','o_level','intermediate','a_level','dae','bachelor','masters'],allowOther:true,isDate:false,step:2},
  {name:'group',fieldKey:'education',required:true,choices:['science_biology','science_computer','arts'],labels:{science_biology:'Science (Biology)',science_computer:'Science (Computer)',arts:'Arts'},isDate:false,step:2,depends_on:{field:'level',values:['matric']}},
  {name:'group',fieldKey:'education',required:true,choices:['pre_engineering','pre_medical','ics','icom','fa_humanities'],isDate:false,step:2,depends_on:{field:'level',values:['intermediate']}},
  {name:'subjects',fieldKey:'education',required:true,multi:true,choices:['mathematics','physics','chemistry','biology','computer_science'],labels:{mathematics:'Mathematics',physics:'Physics',chemistry:'Chemistry',biology:'Biology',computer_science:'Computer Science'},isDate:false,step:2,depends_on:{field:'level',values:['o_level','a_level']}},
  {name:'technology',fieldKey:'education',required:true,choices:['electrical','mechanical','civil'],labels:{electrical:'Electrical',mechanical:'Mechanical',civil:'Civil'},isDate:false,step:2,depends_on:{field:'level',values:['dae']}},
  {name:'field',fieldKey:'education',required:true,searchable:true,choices:['electrical_engineering','computer_science','software_engineering','mbbs','bba'],labels:{electrical_engineering:'Electrical Engineering',computer_science:'Computer Science',software_engineering:'Software Engineering',mbbs:'MBBS (Medicine)',bba:'BBA'},isDate:false,step:2,depends_on:{field:'level',values:['bachelor','masters']}},
  {name:'status',fieldKey:'education',required:true,choices:['current','completed'],isDate:false,step:2,depends_on:{field:'level'}},
  {name:'year',fieldKey:'education',required:true,choices:['year_1','year_2'],labelKey:'currentYear',isDate:false,step:2,depends_on:{field:'status',values:['current'],and:{field:'level',values:['matric','o_level','intermediate','a_level','masters']}}},
  {name:'year',fieldKey:'education',required:true,choices:['year_1','year_2','year_3'],labelKey:'currentYear',isDate:false,step:2,depends_on:{field:'status',values:['current'],and:{field:'level',values:['dae']}}},
  {name:'year',fieldKey:'education',required:true,choices:['semester_1','semester_2','semester_3','semester_4','semester_5','semester_6','semester_7','semester_8'],labelKey:'semester',isDate:false,step:2,depends_on:{field:'status',values:['current'],and:{field:'level',values:['bachelor']}}},
  {name:'year',fieldKey:'education',required:true,choices:[],isYear:true,labelKey:'graduationYear',isDate:false,step:2,depends_on:{field:'status',values:['completed']}},
  {name:'dateOfBirth',fieldKey:'identity.date_of_birth',required:true,choices:[],isDate:true,step:3},
  {name:'gender',fieldKey:'identity.gender',required:true,choices:['male','female','undisclosed'],isDate:false,step:3},
  {name:'currentCountry',fieldKey:'location.current_country',required:true,choices:[],isDate:false,step:3,default:'Pakistan',options:['Pakistan']},
  {name:'currentCity',fieldKey:'location.current_city',required:true,choices:[],isDate:false,step:3},
]};
createRoot(document.getElementById('root')!).render(<ThemeProvider attribute="class" forcedTheme={q.get('theme')||'light'}><I18nProvider><DialogsProvider><LayoutProvider>{authPages[location.pathname]?React.createElement(authPages[location.pathname]):q.has('kit')?<KitGallery/>:q.has('onboarding')?<OnboardingView state={entry as any} onDone={()=>location.assign('/student?view=threads')}/>:<CounselorShell/>}</LayoutProvider></DialogsProvider></I18nProvider></ThemeProvider>);
