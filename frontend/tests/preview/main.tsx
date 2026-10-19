import React from 'react';
import {createRoot} from 'react-dom/client';
import {ThemeProvider} from 'next-themes';
import {I18nProvider} from '@/lib/i18n';
import {DialogsProvider} from '@/components/ui/dialogs-provider';
import {LayoutProvider} from '@/components/layout/layout-context';
import {CounselorShell} from '@/components/counselor/workspace/shell';
import {OnboardingView} from '@/components/onboarding/onboarding-view';
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
createRoot(document.getElementById('root')!).render(<ThemeProvider attribute="class" forcedTheme={q.get('theme')||'light'}><I18nProvider><DialogsProvider><LayoutProvider>{q.has('onboarding')?<OnboardingView state={entry as any} onDone={()=>location.assign('/student?view=threads')}/>:<CounselorShell/>}</LayoutProvider></DialogsProvider></I18nProvider></ThemeProvider>);
