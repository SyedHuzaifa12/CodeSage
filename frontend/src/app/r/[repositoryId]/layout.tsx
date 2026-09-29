"use client";

import { RepositoryProvider, useRepositoryContext } from "@/context/RepositoryContext";
import { NavRail } from "@/components/nav/NavRail";
import { BottomNav } from "@/components/nav/BottomNav";
import { TopBar } from "@/components/nav/TopBar";
import { useBreakpoint } from "@/hooks/useMediaQuery";

function RepoShell({ children }: { children: React.ReactNode }) {
  const { repositoryId, repository, isReady } = useRepositoryContext();
  const breakpoint = useBreakpoint();

  // Fixed viewport-height app shell with an internally-scrolling <main> —
  // required so the mobile BottomNav stays reachable at the bottom of the
  // screen at all times, rather than living at the end of a long
  // document a user has to scroll all the way down to reach.
  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      <TopBar repository={repository} />
      <div className="flex min-h-0 flex-1">
        {breakpoint !== "mobile" && (
          <NavRail repositoryId={repositoryId} ready={isReady} variant={breakpoint === "tablet" ? "tablet" : "desktop"} />
        )}
        <main className="min-w-0 flex-1 overflow-y-auto cs-scrollbar">{children}</main>
      </div>
      {breakpoint === "mobile" && <BottomNav repositoryId={repositoryId} ready={isReady} />}
    </div>
  );
}

export default function RepositoryLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: { repositoryId: string };
}) {
  return (
    <RepositoryProvider repositoryId={params.repositoryId}>
      <RepoShell>{children}</RepoShell>
    </RepositoryProvider>
  );
}
