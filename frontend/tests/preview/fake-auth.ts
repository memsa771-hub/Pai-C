// Preview identity only. Never imports or contacts a real authentication provider.
export const usePaiAuth = () => ({
  user: {id:'offline-student',displayName:'Sam Taylor',email:'student@example.test',photoURL:null},
  isPaiDeployment:true,
  signIn:async()=>{},
  signOut:async()=>{sessionStorage.setItem('offline-sign-out','done');},
});
