import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Roster Lab",
  description: "College basketball roster construction and transfer portal analytics.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `
              (function () {
                try {
                  var stored = window.localStorage.getItem('roster-lab-theme');
                  var mode = stored === 'light' || stored === 'dark' || stored === 'system' ? stored : 'system';
                  var prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
                  var shouldUseDark = mode === 'dark' || (mode === 'system' && prefersDark);
                  document.documentElement.classList.toggle('dark', shouldUseDark);
                  document.documentElement.dataset.theme = mode;
                } catch (error) {}
              })();
            `,
          }}
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
