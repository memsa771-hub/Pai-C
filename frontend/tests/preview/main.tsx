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
const entry={required:true,completedAt:null,prefill:{},fields:[
  {name:'fullName',fieldKey:'identity.full_name',required:true,choices:[],isDate:false},
  {name:'level',fieldKey:'education',required:true,choices:['Catalog level'],allowOther:true,isDate:false},
  {name:'currentCity',fieldKey:'location.current_city',required:true,choices:[],isDate:false},
  {name:'replyLanguage',fieldKey:'preferences.preferred_language',required:true,choices:['english','roman urdu'],isDate:false},
]};
createRoot(document.getElementById('root')!).render(<ThemeProvider attribute="class" forcedTheme={q.get('theme')||'light'}><I18nProvider><DialogsProvider><LayoutProvider>{authPages[location.pathname]?React.createElement(authPages[location.pathname]):q.has('kit')?<KitGallery/>:q.has('onboarding')?<OnboardingView state={entry as any} onDone={()=>location.assign('/student?view=threads')}/>:<CounselorShell/>}</LayoutProvider></DialogsProvider></I18nProvider></ThemeProvider>);
