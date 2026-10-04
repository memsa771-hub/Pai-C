'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import Image from 'next/image';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { completePasswordReset } from '@/lib/auth/service';
import { usePaiAuth } from '@/lib/pai-auth-context';
import { registrationPasswordError } from '@/lib/password-policy';

export default function ResetPasswordPage() {
  const router = useRouter();
  const { applySession } = usePaiAuth();
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (password !== confirm) { setError('Passwords do not match'); return; }
    if (registrationPasswordError(password)) {
      setError('Choose a stronger password with at least 8 characters.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const params = new URLSearchParams(window.location.search);
      const code = params.get('code');
      if (!code || params.get('error')) throw new Error('Recovery link is invalid or expired');
      const session = await completePasswordReset(code, password);
      await applySession(session);
      router.replace('/');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Recovery link is invalid or expired');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center p-8">
      <div className="w-full max-w-sm space-y-5">
        <div className="text-center">
          <Image src="/pai-emblem.png" alt="Placement AI" width={40} height={40}
            className="mx-auto mb-3" />
          <h1 className="text-xl font-semibold">Choose a new password</h1>
        </div>
        <form onSubmit={submit} className="grid gap-4">
          <div className="grid gap-1.5">
            <Label htmlFor="password">New password</Label>
            <Input id="password" type="password" autoComplete="new-password" required
              value={password} onChange={(event) => setPassword(event.target.value)} />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="confirm">Confirm password</Label>
            <Input id="confirm" type="password" autoComplete="new-password" required
              value={confirm} onChange={(event) => setConfirm(event.target.value)} />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <Button type="submit" disabled={busy}>{busy ? 'Updating…' : 'Update password'}</Button>
        </form>
        <p className="text-center text-sm"><Link href="/sign-in" className="hover:underline">Back to sign in</Link></p>
      </div>
    </div>
  );
}
