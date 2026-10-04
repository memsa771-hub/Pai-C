/** Remove credentials left by pre-cookie builds; never persist tokens here. */
export function clearAuthSession(): void {
  try { localStorage.removeItem('oa_supabase_session'); } catch { /* storage disabled */ }
}
