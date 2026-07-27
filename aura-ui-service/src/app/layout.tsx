import './globals.css';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Aura Workspace',
  description: 'AURA Enterprise Workspace',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}