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
import ResetPassword from '@/app/auth/reset-password/page';
import AuthCallback from '@/app/auth/callback/page';
const authPages:Record<string,()=>React.JSX.Element>={'/sign-in':SignIn,'/sign-up':SignUp,'/forgot-password':ForgotPassword,'/auth/reset-password':ResetPassword,'/auth/callback':AuthCallback};
import '@/styles/globals.css';
// Fixture-only entry point: deliberately cannot contact the application or a provider.
window.fetch=async()=>{throw new Error('Network disabled in offline UI review');};
const q=new URLSearchParams(location.search);
const entry={required:true,completedAt:null,prefill:{currentCountry:'Pakistan'},fields:[
  {name:'firstName',fieldKey:'identity.full_name',required:true,choices:[],isDate:false,step:1},
  {name:'lastName',fieldKey:'identity.full_name',required:true,choices:[],isDate:false,step:1},
  {name:'level',fieldKey:'education',required:true,choices:['matric','o-level','fsc','a-level'],allowOther:true,isDate:false,step:2},
  {name:'dateOfBirth',fieldKey:'identity.date_of_birth',required:true,choices:[],isDate:true,step:2},
  {name:'gender',fieldKey:'identity.gender',required:true,choices:['male','female','undisclosed'],isDate:false,step:2},
  {name:'currentCountry',fieldKey:'location.current_country',required:true,choices:[],isDate:false,step:3,default:'Pakistan',options:['Pakistan']},
  {name:'currentCity',fieldKey:'location.current_city',required:true,choices:[],isDate:false,step:3},
]};
createRoot(document.getElementById('root')!).render(<ThemeProvider attribute="class" forcedTheme={q.get('theme')||'light'}><I18nProvider><DialogsProvider><LayoutProvider>{authPages[location.pathname]?React.createElement(authPages[location.pathname]):q.has('kit')?<KitGallery/>:q.has('onboarding')?<OnboardingView state={entry as any} onDone={()=>location.assign('/student?view=threads')}/>:<CounselorShell/>}</LayoutProvider></DialogsProvider></I18nProvider></ThemeProvider>);
