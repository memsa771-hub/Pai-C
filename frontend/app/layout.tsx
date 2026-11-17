import type { Metadata, Viewport } from 'next';
import Script from 'next/script';
import { ThemeProvider } from 'next-themes';
import { Toaster } from '@/components/ui/sonner';
import { PaiAuthProvider } from '@/lib/pai-auth-context';
import { DialogsProvider } from '@/components/ui/dialogs-provider';
import { DEFAULT_LOCALE, I18nProvider } from '@/lib/i18n';
import { getServerTranslations } from '@/lib/i18n/server';
import { gaSnippet, posthogSnippet } from '@/lib/analytics-snippets';
import '@/styles/globals.css';

// Analytics identifiers come from deployment environment variables. When a
// key is unset the corresponding client snippet is skipped entirely.
const POSTHOG_KEY = process.env.NEXT_PUBLIC_POSTHOG_KEY;
const POSTHOG_HOST = process.env.NEXT_PUBLIC_POSTHOG_HOST;
const GA_ID = process.env.NEXT_PUBLIC_GA_ID;

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getServerTranslations();
  return {
    title: t('metadata.title'),
    description: t('metadata.description'),
    ...staticMetadata,
  };
}

const staticMetadata: Metadata = {
  icons: {
    icon: [
      { url: '/favicon-32x32.png', sizes: '32x32', type: 'image/png' },
    ],
    apple: '/favicon-32x32.png',
  },
  manifest: '/site.webmanifest',
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  maximumScale: 1,
  viewportFit: 'cover',
};

export default async function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang={DEFAULT_LOCALE} suppressHydrationWarning>
      <head>
        {POSTHOG_KEY && POSTHOG_HOST && (
        <Script id="posthog-init" strategy="afterInteractive">{posthogSnippet(POSTHOG_KEY, POSTHOG_HOST)}</Script>
        )}
        {GA_ID && (
        <Script id="gtag-init" strategy="afterInteractive">{gaSnippet(GA_ID)}</Script>
        )}
      </head>
      {/* `suppressHydrationWarning` here is for the browser, not for us:
          extensions routinely stamp attributes onto <body> (cz-shortcut-listen,
          grammarly-*, …) before React hydrates, and each one raises a mismatch
          that buries real warnings. Scoped to this element — children still
          report normally. */}
      <body
        className="font-sans bg-background text-foreground antialiased"
        suppressHydrationWarning
      >
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
          <I18nProvider>
            {/* Legacy email/password AuthProvider was removed in v1.0 —
                PaiAuthProvider supplies the canonical identity path. */}
            <PaiAuthProvider>
              <DialogsProvider>
                {children}
              </DialogsProvider>
            </PaiAuthProvider>
            <Toaster />
          </I18nProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
