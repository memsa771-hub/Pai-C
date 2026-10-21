'use client';

import { useState } from 'react';
import type * as React from 'react';
import {
  Check, KeyRound, LogIn, LogOut, User } from 'lucide-react';
import { toast } from 'sonner';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { useConfirm } from '@/components/ui/dialogs-provider';
import { useWorkspace } from '@/lib/workspace-context';
import { usePaiAuth } from '@/lib/pai-auth-context';
import { goToSignIn, signOutAndReturnToSignIn } from '@/lib/auth-redirects';
import { useT } from '@/lib/i18n';

interface UserMenuProps {
  side?: 'top' | 'right' | 'bottom' | 'left';
  align?: 'start' | 'center' | 'end';
  showIdentity?: boolean;
  profileAction?: { label: string; onSelect: () => void; icon?: React.ComponentType };
  /** `avatar`: a 44px initials button for the top bar. */
  variant?: 'default' | 'avatar';
}

export function UserMenu({ side, align = 'end', showIdentity = false, profileAction, variant = 'default' }: UserMenuProps = {}) {
  const { token } = useWorkspace();
  const { user, isPaiDeployment, signIn, signOut } = usePaiAuth();
  const confirm = useConfirm();
  const t = useT();
  const [tokenCopied, setTokenCopied] = useState(false);

  const handleCopyToken = async () => {
    if (!token) {
      toast.error(t('userMenu.tokenMissing'));
      return;
    }
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(token);
      } else {
        // Fallback for in-app browsers / insecure contexts without the Clipboard API
        const ta = document.createElement('textarea');
        ta.value = token;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
      }
      setTokenCopied(true);
      toast.success(t('userMenu.tokenCopiedToast'));
      setTimeout(() => setTokenCopied(false), 2000);
    } catch {
      toast.error(t('userMenu.tokenCopyFailed'));
    }
  };

  // Signing out drops the session on this device — cheap to redo, but not
  // something to trigger from a stray click on a menu item that sits one row
  // below "Workspace settings".
  const handleSignOut = async () => {
    const ok = await confirm({
      title: t('userMenu.signOutTitle'),
      description: user
        ? t('userMenu.signOutDescriptionWithEmail', { email: user.email })
        : t('userMenu.signOutDescription'),
      confirmText: t('userMenu.signOut'),
      destructive: true,
    });
    if (ok) {
      try { await signOutAndReturnToSignIn(signOut); }
      catch { toast.error(t('userMenu.signOutFailed')); }
    }
  };

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            aria-label={t('userMenu.account')}
            title={user?.email || t('userMenu.account')}
            className={`${showIdentity ? 'min-w-0 flex-1 gap-3 rounded-md px-2 py-2 text-left' : variant === 'avatar' ? 'size-11 justify-center rounded-full' : 'size-8 justify-center rounded-full'} flex items-center text-muted-foreground transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring`}
          >
            {user ? (
              <span className={`flex shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-[var(--hero-from)] to-[var(--hero-via)] font-bold text-white ${variant === 'avatar' ? 'size-9 text-sm' : 'size-7 text-xs'}`}>
                {(user.displayName || user.email).charAt(0).toUpperCase()}
              </span>
            ) : (
              <User className="size-4" />
            )}
            {showIdentity && <span className="min-w-0 truncate text-sm font-medium text-sidebar-foreground">
              {user?.displayName || user?.email || t('userMenu.account')}
            </span>}
          </button>
        </DropdownMenuTrigger>

        <DropdownMenuContent side={side} align={align} sideOffset={8} className="w-60">
          {user && (
            <>
              <DropdownMenuLabel className="flex flex-col gap-0.5">
                {user.displayName && <span className="truncate text-sm font-semibold">{user.displayName}</span>}
                <span className="truncate text-xs font-normal text-muted-foreground">{user.email}</span>
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
            </>
          )}

          {profileAction && <DropdownMenuItem onSelect={profileAction.onSelect}>
            {profileAction.icon ? <profileAction.icon /> : <User />}{profileAction.label}
          </DropdownMenuItem>}


          {token && (
            <DropdownMenuItem onSelect={(e) => { e.preventDefault(); handleCopyToken(); }}>
              {tokenCopied ? <Check /> : <KeyRound />}
              {tokenCopied ? t('userMenu.tokenCopied') : t('userMenu.copyToken')}
            </DropdownMenuItem>
          )}


          {/* Settings live in one place: the workspace's own Settings page,
              reached from the sidebar. Appearance is there too. */}

          {isPaiDeployment && (
            <>
              <DropdownMenuSeparator />
              {user ? (
                <DropdownMenuItem onClick={handleSignOut} variant="destructive">
                  <LogOut />
                  {t('userMenu.signOut')}
                </DropdownMenuItem>
              ) : (
                <DropdownMenuItem onClick={() => goToSignIn()}>
                  <LogIn />
                  {t('userMenu.signIn')}
                </DropdownMenuItem>
              )}
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
    </>
  );
}
