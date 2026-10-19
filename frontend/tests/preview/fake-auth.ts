// Preview identity only. Never imports or contacts a real authentication provider.
const authPage = () => ['/sign-in', '/sign-up', '/forgot-password', '/auth/reset-password', '/auth/callback'].includes(location.pathname);
export const usePaiAuth = () => ({
  user: authPage() ? null : {id:'offline-student',displayName:'Sam Taylor',email:'student@example.test',photoURL:null},
  loading: false,
  idToken: null,
  isPaiDeployment:true,
  applySession: async () => {},
  signIn:async()=>{},
  signOut:async()=>{sessionStorage.setItem('offline-sign-out','done');},
});
