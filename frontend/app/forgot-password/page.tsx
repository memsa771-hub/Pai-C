'use client';

import { useState } from 'react';
import Link from 'next/link';
import Image from 'next/image';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { requestPasswordReset } from '@/lib/auth/service';

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('');
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      await requestPasswordReset(email.trim());
      setSent(true);
    } catch {
      setError('Password recovery is temporarily unavailable. Please try again.');
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
          <h1 className="text-xl font-semibold">Reset password</h1>
        </div>
        {sent ? (
          <p className="text-sm text-muted-foreground">
            If an account exists for that email, we sent reset instructions.
          </p>
        ) : (
          <form onSubmit={submit} className="grid gap-4">
            <div className="grid gap-1.5">
              <Label htmlFor="email">Email</Label>
              <Input id="email" type="email" autoComplete="email" required
                value={email} onChange={(event) => setEmail(event.target.value)} />
            </div>
            {error && <p className="text-sm text-destructive">{error}</p>}
            <Button type="submit" disabled={busy}>{busy ? 'Sending…' : 'Send reset instructions'}</Button>
          </form>
        )}
        <p className="text-center text-sm"><Link href="/sign-in" className="hover:underline">Back to sign in</Link></p>
      </div>
    </div>
  );
}
