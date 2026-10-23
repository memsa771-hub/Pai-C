'use client';

/** Where an email/password account waits until its address is verified. */

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { AuthShell } from '@/components/auth/auth-shell';
import { CheckEmailStatus } from '@/components/auth/check-email';
import { onUserChange } from '@/lib/auth/service';

export default function VerifyEmailPage() {
  const router = useRouter();
  const [email, setEmail] = useState<string | null>(null);

  useEffect(() => onUserChange((user) => {
    if (!user) router.replace('/sign-in');
    else if (user.emailVerified) router.replace('/');
    else setEmail(user.email || '');
  }), [router]);

  if (email === null) return null;
  return (
    <AuthShell>
      <CheckEmailStatus email={email} justSent={false} />
    </AuthShell>
  );
}
