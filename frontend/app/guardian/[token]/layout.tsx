import type { Metadata } from 'next';

// The link is the credential: no referrer leaves this page, and search engines keep out.
export const metadata: Metadata = {
  referrer: 'no-referrer',
  robots: { index: false, follow: false },
};

export default function GuardianLayout({ children }: { children: React.ReactNode }) {
  return children;
}
