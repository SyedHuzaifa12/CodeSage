import Link from "next/link";
import { TopologyMark } from "@/components/devices/TopologyMark";

export default function NotFound() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 text-center">
      <TopologyMark variant="mark" size={32} />
      <h1 className="font-display text-display italic text-text-primary">Page not found</h1>
      <Link href="/" className="font-mono text-[11px] text-violet hover:underline">
        Back to Repositories &rarr;
      </Link>
    </div>
  );
}
